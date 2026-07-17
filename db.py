"""
Data access layer for QueueZero AI — replaces gsheet.py entirely.

Every function here talks to Supabase (Postgres) instead of a spreadsheet.
These are plain Python functions with no LLM logic in them; tools.py wraps
them as Claude tool calls.
"""

import os
import threading
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from supabase import create_client

from distance import haversine_km

load_dotenv()

# .strip() guards against trailing whitespace/newlines pasted into the env var
# (e.g. a copy-pasted Railway value), which would otherwise reach create_client
# as part of the hostname and fail DNS with "[Errno -2] Name or service not
# known". "" -> None so the "if not SUPABASE_URL" check below still fires.
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").strip() or None
SUPABASE_KEY = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip() or None

_client = None
_local = threading.local()


def set_booking_user(user_id):
    """Store the authenticated user_id on the current thread so book_slot can tag the appointment."""
    _local.user_id = user_id


def clear_booking_user():
    _local.user_id = None


def get_client():
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (env vars or .env file)."
            )
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ------------------------------------------------------------------
# Hospitals
# ------------------------------------------------------------------
def search_hospitals(city=None, near_latitude=None, near_longitude=None, max_distance_km=None):
    client = get_client()
    query = client.table("hospitals").select("*")
    if city:
        query = query.ilike("city", f"%{city}%")
    rows = query.execute().data

    for h in rows:
        h["distance_km"] = haversine_km(near_latitude, near_longitude, h["latitude"], h["longitude"])

    if max_distance_km is not None and near_latitude is not None:
        rows = [h for h in rows if h["distance_km"] is not None and h["distance_km"] <= max_distance_km]

    rows.sort(key=lambda h: (h["distance_km"] is None, h["distance_km"] or 0))
    return rows


# ------------------------------------------------------------------
# Doctors (using the doctor_search_view: doctor + hospital + live queue joined)
# ------------------------------------------------------------------
def find_doctors(specialization=None, gender=None, hospital_id=None, min_rating=None,
                  max_wait_minutes=None, city=None, near_latitude=None, near_longitude=None,
                  max_distance_km=None, limit=25):
    client = get_client()
    query = client.table("doctor_search_view").select("*")

    if specialization:
        query = query.ilike("specialization", f"%{specialization}%")
    if gender:
        query = query.eq("gender", gender)
    if hospital_id:
        query = query.eq("hospital_id", hospital_id)
    if min_rating is not None:
        query = query.gte("rating", min_rating)
    if max_wait_minutes is not None:
        query = query.lte("average_wait_mins", max_wait_minutes)
    if city:
        query = query.ilike("city", f"%{city}%")

    rows = query.limit(limit).execute().data

    for d in rows:
        d["distance_km"] = haversine_km(near_latitude, near_longitude, d["latitude"], d["longitude"])

    if max_distance_km is not None and near_latitude is not None:
        rows = [d for d in rows if d["distance_km"] is not None and d["distance_km"] <= max_distance_km]

    return rows


# ------------------------------------------------------------------
# Schedules / slots
# ------------------------------------------------------------------
def find_available_slots(doctor_id, target_date=None, after_time=None, before_time=None, days_ahead=4):
    """
    Returns available slots for a doctor.
    If target_date is None, scans the next `days_ahead` days and returns the
    earliest matches first (so the agent can answer "earliest after 3pm").
    """
    client = get_client()
    dates_to_check = (
        [target_date] if target_date else
        [(date.today() + timedelta(days=i)).isoformat() for i in range(days_ahead)]
    )

    results = []
    for d in dates_to_check:
        row = (
            client.table("schedules")
            .select("*")
            .eq("doctor_id", doctor_id)
            .eq("date", d)
            .maybe_single()
            .execute()
        )
        if not row or not row.data:
            continue
        schedule = row.data
        for slot in schedule["slots"]:
            if not slot["is_available"]:
                continue
            if after_time and slot["time"] < after_time:
                continue
            if before_time and slot["time"] > before_time:
                continue
            results.append({
                "schedule_id": schedule["id"],
                "doctor_id": doctor_id,
                "date": d,
                "time": slot["time"],
            })

    results.sort(key=lambda s: (s["date"], s["time"]))
    return results


# ------------------------------------------------------------------
# Booking
# ------------------------------------------------------------------
def book_slot(doctor_id, target_date, target_time, patient_name, patient_id=None, is_emergency=False):
    client = get_client()

    schedule_row = (
        client.table("schedules")
        .select("*")
        .eq("doctor_id", doctor_id)
        .eq("date", target_date)
        .maybe_single()
        .execute()
    )
    if not schedule_row or not schedule_row.data:
        return {"success": False, "error": "No schedule found for that doctor/date."}

    schedule = schedule_row.data
    slots = schedule["slots"]
    matched = next((s for s in slots if s["time"] == target_time), None)
    if not matched:
        return {"success": False, "error": "That time slot doesn't exist on this doctor's schedule."}
    if not matched["is_available"]:
        return {"success": False, "error": "That slot was just booked by someone else. Pick another."}

    # mark the slot unavailable
    for s in slots:
        if s["time"] == target_time:
            s["is_available"] = False
    client.table("schedules").update({"slots": slots}).eq("id", schedule["id"]).execute()

    doctor_row = client.table("doctor_search_view").select("*").eq("doctor_id", doctor_id).maybe_single().execute()
    doctor = doctor_row.data if doctor_row else {}

    appointment = {
        "patient_name": patient_name,
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "hospital_id": doctor.get("hospital_id"),
        "appointment_date": target_date,
        "appointment_time": target_time,
        "status": "booked",
        "is_emergency": is_emergency,
        "user_id": getattr(_local, "user_id", None),
    }
    try:
        inserted = client.table("appointments").insert(appointment).execute()
    except Exception as exc:
        err = str(exc)
        # Postgres unique-violation code 23505 — another request just took this slot
        if "23505" in err or "duplicate" in err.lower() or "unique" in err.lower():
            alternatives = find_available_slots(doctor_id, days_ahead=7)
            alternatives = [
                s for s in alternatives
                if not (s["date"] == target_date and s["time"] == target_time)
            ][:3]
            alt_str = ", ".join(f"{s['date']} {s['time']}" for s in alternatives)
            return {
                "success": False,
                "error": (
                    "That slot was just taken by another user. "
                    f"Nearest alternatives: {alt_str or 'none found — try a different doctor'}"
                ),
            }
        raise

    return {
        "success": True,
        "appointment": inserted.data[0] if inserted.data else appointment,
        "doctor_name": doctor.get("doctor_name"),
        "hospital_name": doctor.get("hospital_name"),
        "estimated_wait_mins": doctor.get("average_wait_mins"),
        "waiting_people": doctor.get("waiting_people"),
    }


# ------------------------------------------------------------------
# Emergency queue jump — same booking path, marked is_emergency + logs override
# ------------------------------------------------------------------
def emergency_book(doctor_id, patient_name, patient_id=None):
    """Books the very next available slot today for this doctor, flagged emergency."""
    today = date.today().isoformat()
    now_time = datetime.now().strftime("%H:%M")
    slots = find_available_slots(doctor_id, target_date=today, after_time=now_time)
    if not slots:
        # fall back to next available slot on any day
        slots = find_available_slots(doctor_id)
    if not slots:
        return {"success": False, "error": "No slots available at all for this doctor."}

    next_slot = slots[0]
    result = book_slot(doctor_id, next_slot["date"], next_slot["time"], patient_name, patient_id, is_emergency=True)
    result["priority_override"] = True
    return result


# ------------------------------------------------------------------
# Patients (for memory / preferences, used by the agent's memory layer later)
# ------------------------------------------------------------------
def find_patient_by_name(name):
    client = get_client()
    row = client.table("patients").select("*").ilike("name", f"%{name}%").limit(1).execute()
    return row.data[0] if row.data else None


# ------------------------------------------------------------------
# Notifications (demo stub — swap in real SMS/email/push later)
# ------------------------------------------------------------------
def send_notification(patient_name, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[NOTIFY {timestamp}] To {patient_name}: {message}")
    return {"success": True, "delivered_at": timestamp}


# ------------------------------------------------------------------
# User bookings (history + cancellation)
# ------------------------------------------------------------------
CANCEL_REASONS = {
    "schedule_conflict", "found_another_doctor", "recovered",
    "emergency", "booked_by_mistake", "other",
}


def get_user_bookings(user_id: str):
    client = get_client()
    result = (
        client.table("appointments")
        .select("*")
        .eq("user_id", user_id)
        .order("appointment_date", desc=True)
        .order("appointment_time", desc=True)
        .execute()
    )
    bookings = result.data or []

    # Batch-enrich with doctor/hospital names (one query per unique doctor_id)
    seen = {}
    for b in bookings:
        did = b.get("doctor_id")
        if did and did not in seen:
            doc = (
                client.table("doctor_search_view")
                .select("doctor_id, doctor_name, hospital_name")
                .eq("doctor_id", did)
                .maybe_single()
                .execute()
            )
            seen[did] = doc.data if (doc and doc.data) else {}
        info = seen.get(did, {})
        b["doctor_name"] = info.get("doctor_name")
        b["hospital_name"] = info.get("hospital_name")

    return bookings


def cancel_booking(booking_id: str, user_id: str, reason: str, reason_detail: str = None):
    if reason not in CANCEL_REASONS:
        return {"success": False, "error": f"Invalid reason. Valid options: {', '.join(sorted(CANCEL_REASONS))}"}
    if reason == "other" and not (reason_detail or "").strip():
        return {"success": False, "error": "reason_detail is required when reason is 'other'."}

    client = get_client()
    row = (
        client.table("appointments")
        .select("*")
        .eq("id", booking_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not row or not row.data:
        return {"success": False, "error": "Booking not found or does not belong to you."}

    booking = row.data
    if booking["status"] == "cancelled":
        return {"success": False, "error": "Booking is already cancelled."}

    # 1. Mark appointment cancelled
    client.table("appointments").update({"status": "cancelled"}).eq("id", booking_id).execute()

    # 2. Free the slot back in schedules so it can be rebooked
    sched = (
        client.table("schedules")
        .select("*")
        .eq("doctor_id", booking["doctor_id"])
        .eq("date", booking["appointment_date"])
        .maybe_single()
        .execute()
    )
    if sched and sched.data:
        slots = sched.data["slots"]
        for s in slots:
            if s["time"] == booking["appointment_time"]:
                s["is_available"] = True
        client.table("schedules").update({"slots": slots}).eq("id", sched.data["id"]).execute()

    # 3. Record the cancellation for audit / analytics
    client.table("cancellations").insert({
        "booking_id": booking_id,
        "user_id": user_id,
        "reason": reason,
        "reason_detail": reason_detail or None,
    }).execute()

    # 4. Return total cancellation count for the user (shown in UI)
    count_res = (
        client.table("cancellations")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    cancel_count = count_res.count if count_res.count is not None else len(count_res.data or [])
    return {"success": True, "cancellation_count": cancel_count}


# ------------------------------------------------------------------
# Admin dashboard stats
# ------------------------------------------------------------------
def get_admin_stats():
    client = get_client()
    today_str = date.today().isoformat()

    # Doctor/hospital info — single query covers names + hospital mapping
    doctor_rows = (
        client.table("doctor_search_view")
        .select("doctor_id, hospital_id, doctor_name, hospital_name")
        .execute()
        .data or []
    )
    doctor_info = {}
    doctor_to_hospital = {}
    hospital_names = {}
    for d in doctor_rows:
        did, hid = d["doctor_id"], d.get("hospital_id")
        doctor_info[did] = {"doctor_name": d.get("doctor_name"), "hospital_name": d.get("hospital_name")}
        doctor_to_hospital[did] = hid
        if hid and hid not in hospital_names:
            hospital_names[hid] = d.get("hospital_name")

    # Slot totals from schedules — aggregate in Python, not DB
    schedules = client.table("schedules").select("doctor_id, slots").execute().data or []
    total_slots = available_slots = 0
    h_total = {}
    h_avail = {}
    for sched in schedules:
        slots = sched.get("slots") or []
        hid = doctor_to_hospital.get(sched.get("doctor_id"))
        avail = sum(1 for s in slots if s.get("is_available"))
        total_slots += len(slots)
        available_slots += avail
        if hid:
            h_total[hid] = h_total.get(hid, 0) + len(slots)
            h_avail[hid] = h_avail.get(hid, 0) + avail

    # Bookings today
    today_res = (
        client.table("appointments")
        .select("id", count="exact")
        .eq("appointment_date", today_str)
        .neq("status", "cancelled")
        .execute()
    )
    today_count = today_res.count or 0

    # Recent bookings enriched from doctor_info (no per-row queries)
    recent = (
        client.table("appointments")
        .select("*")
        .neq("status", "cancelled")
        .order("appointment_date", desc=True)
        .order("appointment_time", desc=True)
        .limit(30)
        .execute()
        .data or []
    )
    for b in recent:
        info = doctor_info.get(b.get("doctor_id"), {})
        b["doctor_name"] = info.get("doctor_name")
        b["hospital_name"] = info.get("hospital_name")

    hospital_capacity = sorted(
        [
            {
                "hospital_id": hid,
                "hospital_name": hospital_names.get(hid, "Unknown"),
                "total": total,
                "available": h_avail.get(hid, 0),
                "booked": total - h_avail.get(hid, 0),
            }
            for hid, total in h_total.items()
        ],
        key=lambda x: x["booked"],
        reverse=True,
    )

    return {
        "counters": {
            "total": total_slots,
            "booked": total_slots - available_slots,
            "available": available_slots,
            "today": today_count,
        },
        "recent_bookings": recent,
        "hospital_capacity": hospital_capacity,
        "doctor_lookup": doctor_info,
    }
