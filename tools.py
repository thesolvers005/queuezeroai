"""
Tool definitions for the QueueZero agent, in Anthropic tool-use format,
plus the dispatcher that executes them against db.py.

Claude decides which of these to call and in what order — this file just
describes the tools and wires calls through to the real data layer.
"""

import threading

import db
import locations

TOOL_DEFINITIONS = [
    {
        "name": "resolve_location",
        "description": (
            "Convert a place name the user mentioned (e.g. 'Mangalagiri', 'Hyderabad') "
            "into latitude/longitude, so you can then filter hospitals/doctors by "
            "distance from it. Call this BEFORE search_hospitals or find_doctors "
            "whenever the user names a place instead of giving you coordinates directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"place_name": {"type": "string"}},
            "required": ["place_name"],
        },
    },
    {
        "name": "search_hospitals",
        "description": (
            "Search hospitals, optionally filtered by city and/or distance from the "
            "user's location. Use this when the user cares about which hospital/branch, "
            "or mentions a travel-distance preference."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name to filter by, e.g. 'Vijayawada'."},
                "near_latitude": {"type": "number", "description": "User's latitude, if known."},
                "near_longitude": {"type": "number", "description": "User's longitude, if known."},
                "max_distance_km": {"type": "number", "description": "Max travel distance in km from the user's location."},
            },
        },
    },
    {
        "name": "find_doctors",
        "description": (
            "Search doctors by specialization, gender, minimum rating, hospital, city, "
            "max current wait time, and/or distance from the user. Returns rating, "
            "experience, current queue length, and average wait per doctor. This is "
            "usually the first real search after understanding what the user needs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "specialization": {"type": "string", "description": "e.g. 'Cardiology', 'Dermatology'."},
                "gender": {"type": "string", "enum": ["male", "female"]},
                "hospital_id": {"type": "string", "description": "Restrict to one hospital's doctors."},
                "min_rating": {"type": "number", "description": "Minimum doctor rating, 0-5."},
                "max_wait_minutes": {"type": "number", "description": "Max acceptable current average wait time."},
                "city": {"type": "string"},
                "near_latitude": {"type": "number"},
                "near_longitude": {"type": "number"},
                "max_distance_km": {"type": "number"},
            },
        },
    },
    {
        "name": "find_available_slots",
        "description": (
            "Get available appointment slots for a specific doctor. If target_date is "
            "omitted, scans the next few days and returns the earliest matches first — "
            "use this for requests like 'earliest slot after 3pm'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string"},
                "target_date": {"type": "string", "description": "YYYY-MM-DD. Omit to search the next few days."},
                "after_time": {"type": "string", "description": "HH:MM, 24-hour. Only slots at or after this time."},
                "before_time": {"type": "string", "description": "HH:MM, 24-hour. Only slots at or before this time."},
            },
            "required": ["doctor_id"],
        },
    },
    {
        "name": "book_slot",
        "description": "Book a specific date/time slot for a doctor under a patient's name. Only call this after the user has confirmed (or clearly implied) which option they want.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string"},
                "target_date": {"type": "string", "description": "YYYY-MM-DD"},
                "target_time": {"type": "string", "description": "HH:MM, 24-hour"},
                "patient_name": {"type": "string"},
                "patient_id": {"type": "string", "description": "Optional, if this is a known demo patient."},
            },
            "required": ["doctor_id", "target_date", "target_time", "patient_name"],
        },
    },
    {
        "name": "emergency_book",
        "description": (
            "Emergency priority booking: books the next available slot today for the "
            "given doctor, overriding normal queue order. Use only when the user "
            "describes an urgent/emergency situation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string"},
                "patient_name": {"type": "string"},
                "patient_id": {"type": "string"},
            },
            "required": ["doctor_id", "patient_name"],
        },
    },
    {
        "name": "find_patient_by_name",
        "description": "Look up a demo patient record by name, e.g. to recall stored preferences.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "send_notification",
        "description": "Send a confirmation/notification message to the patient after booking (or after a failed search, if useful).",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["patient_name", "message"],
        },
    },
]

def _send_notification(patient_name, message):
    """
    The agent's in-conversation notification step — a lightweight log stub only.

    The confirmation *email* is no longer sent here: it is dispatched
    automatically by the request handler right after a successful booking
    (see app.py), so it fires unconditionally and per-request rather than
    depending on the model choosing to call this tool, and without any
    module-level booking/recipient state that could leak across concurrent
    requests.
    """
    return db.send_notification(patient_name, message)


_DISPATCH = {
    "resolve_location": locations.resolve_location,
    "search_hospitals": db.search_hospitals,
    "find_doctors": db.find_doctors,
    "find_available_slots": db.find_available_slots,
    "book_slot": db.book_slot,
    "emergency_book": db.emergency_book,
    "find_patient_by_name": db.find_patient_by_name,
    "send_notification": _send_notification,
}


def to_openai_tools(tool_definitions):
    """
    Converts our Anthropic-format TOOL_DEFINITIONS into the OpenAI/Ollama
    function-calling format, so the same tool list works with local models
    via Ollama without maintaining two separate schemas.
    """
    converted = []
    for t in tool_definitions:
        converted.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        })
    return converted


def _sanitize_output(name, output):
    """
    Strip internal IDs from tool results before they reach Claude.
    Keep only user-facing fields: names, ratings, times, distances.
    Never expose raw UUIDs or database IDs to the user.
    """
    if isinstance(output, dict) and "error" in output:
        return output  # errors pass through as-is

    if name == "find_doctors" and isinstance(output, list):
        sanitized = []
        for doc in output:
            sanitized.append({
                "doctor_name": doc.get("doctor_name"),
                "specialization": doc.get("specialization"),
                "gender": doc.get("gender"),
                "experience_years": doc.get("experience_years"),
                "rating": doc.get("rating"),
                "average_wait_mins": doc.get("average_wait_mins"),
                "waiting_people": doc.get("waiting_people"),
                "hospital_name": doc.get("hospital_name"),
                "city": doc.get("city"),
                "distance_km": doc.get("distance_km"),
                "doctor_id": doc.get("doctor_id"),  # internal only, for next tool call
            })
        return sanitized

    if name == "search_hospitals" and isinstance(output, list):
        sanitized = []
        for hosp in output:
            sanitized.append({
                "hospital_name": hosp.get("name"),
                "city": hosp.get("city"),
                "address": hosp.get("address"),
                "phone": hosp.get("phone"),
                "distance_km": hosp.get("distance_km"),
                "hospital_id": hosp.get("id"),  # internal only
            })
        return sanitized

    if name == "find_available_slots" and isinstance(output, list):
        sanitized = []
        for slot in output:
            sanitized.append({
                "date": slot.get("date"),
                "time": slot.get("time"),
            })
        return sanitized

    if name == "book_slot" and isinstance(output, dict):
        if output.get("success"):
            appt = output.get("appointment", {})
            return {
                "success": True,
                "doctor_name": output.get("doctor_name"),
                "hospital_name": output.get("hospital_name"),
                "appointment_date": appt.get("appointment_date"),
                "appointment_time": appt.get("appointment_time"),
                "estimated_wait_mins": output.get("estimated_wait_mins"),
            }
        return output  # error, pass through

    if name == "emergency_book" and isinstance(output, dict):
        if output.get("success"):
            appt = output.get("appointment", {})
            return {
                "success": True,
                "doctor_name": output.get("doctor_name"),
                "hospital_name": output.get("hospital_name"),
                "appointment_date": appt.get("appointment_date"),
                "appointment_time": appt.get("appointment_time"),
                "priority_override": True,
            }
        return output

    if name == "find_patient_by_name" and isinstance(output, dict):
        return {
            "patient_name": output.get("name"),
            "preferred_specialization": output.get("preferred_specialization"),
            "preferred_gender": output.get("preferred_gender"),
        }

    # resolve_location, send_notification: pass through
    return output



# ------------------------------------------------------------------
# Optional live-streaming hook for execute_tool (used by the SSE endpoint).
#
# execute_tool is the one place every provider's tool-calling loop already
# funnels through, so it's the single clean spot to observe real dispatch
# timing -- rather than threading an `emit` param through each provider's
# run_agent loop (claude_provider.py's loop is off-limits for this change),
# a per-thread hook here gives the same truthful pending/complete timing
# with zero changes to any provider file. Set via set_emit_hook() from the
# SAME worker thread that then calls run_agent(), so threading.local keeps
# concurrent requests (different threads) fully isolated; the non-streaming
# callers never call set_emit_hook, so _local.emit stays None and
# execute_tool behaves exactly as before.
# ------------------------------------------------------------------
_local = threading.local()

STEP_LABELS = {
    "resolve_location": ("📍 Resolving location", "📍 Location resolved"),
    "search_hospitals": ("🏥 Searching hospitals", "🏥 {n} hospitals found"),
    "find_doctors": ("🏥 Searching nearby doctors", "🏥 {n} doctors found"),
    "find_available_slots": ("⏰ Checking availability", "⏰ {n} slots found"),
    "book_slot": ("📋 Booking appointment", "✓ Appointment booked"),
    "emergency_book": ("🚨 Booking emergency appointment", "✓ Emergency appointment booked"),
    "find_patient_by_name": ("🔍 Looking up patient", "🔍 Patient lookup complete"),
    "send_notification": ("📧 Sending confirmation", "✓ Confirmation sent"),
}


def set_emit_hook(emit):
    """Install a per-thread callback that execute_tool fires around each real
    dispatch. Call this from the worker thread right before run_agent(), and
    clear_emit_hook() in a finally block once it returns."""
    _local.emit = emit
    _local.counter = 0


def clear_emit_hook():
    _local.emit = None


def _step_details(name, output):
    """Truthful, human-readable detail string pulled from the real tool output."""
    if name in ("find_doctors", "search_hospitals", "find_available_slots"):
        return f"{len(output)} found" if isinstance(output, list) else ""
    if name in ("book_slot", "emergency_book") and isinstance(output, dict):
        return f"{output.get('doctor_name')} — {output.get('appointment_date')} {output.get('appointment_time')}"
    if name == "resolve_location":
        if isinstance(output, dict):
            return f"{output.get('latitude')}, {output.get('longitude')}"
        return "location not recognized"
    if name == "find_patient_by_name":
        return output.get("name") if isinstance(output, dict) else "no matching patient"
    if name == "send_notification":
        return "delivered" if isinstance(output, dict) and output.get("success") else ""
    return ""


def execute_tool(name, tool_input):
    emit = getattr(_local, "emit", None)
    step_id = None
    pending_label = name

    if emit is not None:
        pending_label, _ = STEP_LABELS.get(name, (name, name))
        _local.counter += 1
        step_id = _local.counter
        emit({"id": step_id, "step": pending_label, "status": "pending", "details": ""})

    if name not in _DISPATCH:
        output = {"error": f"Unknown tool: {name}"}
    else:
        try:
            raw_output = _DISPATCH[name](**tool_input)
            output = _sanitize_output(name, raw_output)
        except Exception as exc:
            output = {"error": str(exc)}

    if emit is not None:
        _, complete_label = STEP_LABELS.get(name, (name, name))
        is_error = (
            (isinstance(output, dict) and "error" in output)
            or (name == "resolve_location" and output is None)
        )
        if is_error:
            message = output.get("error") if isinstance(output, dict) else "location not recognized"
            emit({"id": step_id, "step": pending_label, "status": "error", "details": message})
        else:
            details = _step_details(name, output)
            label = complete_label.format(n=len(output)) if "{n}" in complete_label else complete_label
            emit({"id": step_id, "step": label, "status": "complete", "details": details})

    return output