"""
Emergency mode detection and handling.

- should_trigger_emergency(text): keyword scan -> bool
- get_emergency_system_prompt_injection(): extra system-prompt block that the
  backend passes into run_agent(extra_system=...) so the agent actually changes
  its booking behavior (this is the piece that makes emergency mode real).
- mark_emergency_booking(): audit-log a priority booking for escalation.
"""

from datetime import datetime
from typing import Dict, List

# Phrases that trigger emergency mode. Kept specific to reduce false positives
# (a bare "urgent" is included but two-word clinical phrases are preferred).
EMERGENCY_KEYWORDS = [
    "chest pain", "heart attack", "cardiac arrest",
    "difficulty breathing", "can't breathe", "shortness of breath",
    "severe bleeding", "heavy bleeding", "bleeding badly",
    "stroke", "seizure", "unconscious", "unresponsive",
    "loss of consciousness", "overdose", "poisoning",
    "allergic reaction", "anaphylaxis", "severe burn",
    "emergency", "urgent", "critical condition",
]

# In-memory audit trail of emergency bookings (for a supervisor dashboard).
EMERGENCY_LOG: List[Dict] = []


def should_trigger_emergency(user_message: str) -> bool:
    """Return True if the message contains an emergency phrase."""
    if not user_message:
        return False
    text = user_message.lower()
    return any(keyword in text for keyword in EMERGENCY_KEYWORDS)


def get_emergency_system_prompt_injection() -> str:
    """
    Extra instructions appended to the base system prompt when emergency mode
    is active. Overrides the normal booking logic with priority handling.

    Passed to run_agent via extra_system so it takes effect for that turn.
    """
    return """# EMERGENCY MODE ACTIVE

This is a medical emergency. Override the normal booking rules above:

1. URGENCY OVERRIDE: book the very next available slot today for a suitable
   doctor, regardless of rating or distance. If no slot is open today, book the
   earliest available slot instead. Waive the patient's distance and wait-time
   preferences.
2. ANY SUITABLE DOCTOR: if the patient's preferred specialist isn't available,
   book any available doctor in that specialty. Do not stall waiting for a
   perfect match.
3. USE emergency_book: call the emergency_book tool (not book_slot) so the
   booking is flagged as priority and jumps the normal queue.
4. DO NOT ask clarifying questions and DO NOT relax-then-confirm. Act now, then
   explain clearly that you overrode the normal queue for an emergency.
5. Remind the patient that if the condition is life-threatening they should call
   emergency services / go to the nearest ER immediately."""


def mark_emergency_booking(appointment: Dict, reason: str) -> Dict:
    """
    Log an emergency booking for audit + escalation.

    In production this would also notify on-call staff and flag the row in the
    hospital's priority queue. Here it appends to EMERGENCY_LOG and prints.
    """
    record = {
        "timestamp": datetime.now().isoformat(),
        "doctor_name": appointment.get("doctor_name"),
        "hospital_name": appointment.get("hospital_name"),
        "appointment_date": appointment.get("appointment_date"),
        "appointment_time": appointment.get("appointment_time"),
        "reason": reason,
        "status": "booked_priority",
    }
    EMERGENCY_LOG.append(record)

    print(
        f"[EMERGENCY] {reason} -> booked {appointment.get('doctor_name')} "
        f"at {appointment.get('appointment_date')} {appointment.get('appointment_time')}"
    )
    return record


def get_emergency_log() -> List[Dict]:
    """Return a copy of the emergency booking log (for an admin view)."""
    return list(EMERGENCY_LOG)


def clear_emergency_log():
    """Clear the log (test helper)."""
    EMERGENCY_LOG.clear()
