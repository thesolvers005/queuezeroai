"""
Data access layer for QueueZero AI — replaces gsheet.py entirely.

Every function here talks to Supabase (Postgres) instead of a spreadsheet.
These are plain Python functions with no LLM logic in them; tools.py wraps
them as Claude tool calls.
"""

import os
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from supabase import create_client

from distance import haversine_km

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

_client = None


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
    }
    inserted = client.table("appointments").insert(appointment).execute()

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
