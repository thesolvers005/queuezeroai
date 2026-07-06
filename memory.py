"""
Patient memory + conversation history layer.

ConversationHistory: holds the canonical message list for a session (the same
    list run_agent consumes and returns), so multi-turn context is preserved.
PatientMemory: stores long-term patient preferences + booking history, and can
    format them as a system-prompt injection so the agent recalls them.

Both are in-memory for the demo. Swap PatientMemory's dict for the Supabase
`patients` table when going past demo data -- the method signatures stay the same.
"""

from datetime import datetime
from typing import Optional, List, Dict


class ConversationHistory:
    """
    Holds the message list for one session.

    IMPORTANT: run_agent() already appends the incoming user message and its
    own assistant/tool messages, and returns the full updated list as
    result["history"]. So the flow is:

        msgs = history.get_messages()
        result = run_agent(user_msg, conversation_history=msgs, ...)
        history.set_messages(result["history"])

    Do NOT also call add_user_message() around run_agent -- that double-adds.
    add_user_message/add_assistant_message exist only for the mock path in
    app.py, which manages messages manually.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: List[Dict] = []
        self.created_at = datetime.now()

    def get_messages(self) -> List[Dict]:
        """Return a shallow copy of the message list to pass into run_agent."""
        return list(self.messages)

    def set_messages(self, messages: List[Dict]):
        """Replace with the updated history returned by run_agent."""
        self.messages = list(messages) if messages else []

    def add_user_message(self, content: str):
        """Mock-path helper: append a user message."""
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        """Mock-path helper: append an assistant message."""
        self.messages.append({"role": "assistant", "content": content})

    def last_user_message(self) -> str:
        """Return the most recent user message text (used for memory notes)."""
        for msg in reversed(self.messages):
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                return msg["content"]
        return ""

    def clear(self):
        self.messages = []

    def __len__(self):
        return len(self.messages)


class PatientMemory:
    """
    Stores patient preferences + booking history across sessions.

    In production this maps to the Supabase `patients` table. For the demo it's
    a plain dict keyed by patient name.
    """

    def __init__(self):
        self.patients: Dict[str, Dict] = {}

    def save(
        self,
        patient_name: str,
        specialization: Optional[str] = None,
        gender: Optional[str] = None,
        hospital: Optional[str] = None,
        notes: Optional[str] = None,
        last_booking: Optional[Dict] = None,
    ):
        """Create or update a patient record. Only non-None fields are updated."""
        if not patient_name:
            return

        record = self.patients.setdefault(
            patient_name,
            {"created_at": datetime.now().isoformat(), "bookings": []},
        )

        if specialization:
            record["preferred_specialization"] = specialization
        if gender:
            record["preferred_gender"] = gender
        if hospital:
            record["preferred_hospital"] = hospital
        if notes:
            record["notes"] = notes

        if last_booking:
            record["bookings"].append({
                "timestamp": datetime.now().isoformat(),
                **last_booking,
            })
            record["last_booking"] = last_booking

        record["updated_at"] = datetime.now().isoformat()

    def get(self, patient_name: str) -> Optional[Dict]:
        """Return the full patient record, or None."""
        return self.patients.get(patient_name)

    def get_context_for_agent(self, patient_name: str) -> str:
        """
        Format the patient's known preferences + last booking as a block of
        text to append to the agent's system prompt (via run_agent's
        extra_system arg). Returns "" if nothing is known, so callers can
        safely concatenate.

        Example:
            Known context for returning patient "Lakshmi Reddy":
            - Preferred specialization: Cardiology
            - Preferred doctor gender: female
            - Last booking: Dr. Sneha Prasad on 2026-07-05
            Use these as sensible defaults if the patient doesn't specify, but
            let anything they say now override them.
        """
        patient = self.get(patient_name)
        if not patient:
            return ""

        lines = [f'Known context for returning patient "{patient_name}":']
        if patient.get("preferred_specialization"):
            lines.append(f"- Preferred specialization: {patient['preferred_specialization']}")
        if patient.get("preferred_gender"):
            lines.append(f"- Preferred doctor gender: {patient['preferred_gender']}")
        if patient.get("preferred_hospital"):
            lines.append(f"- Preferred hospital: {patient['preferred_hospital']}")
        if patient.get("notes"):
            lines.append(f"- Notes: {patient['notes']}")
        if patient.get("last_booking"):
            last = patient["last_booking"]
            lines.append(
                f"- Last booking: {last.get('doctor_name')} on {last.get('appointment_date')}"
            )

        # Only the header line means nothing useful is stored yet.
        if len(lines) == 1:
            return ""

        lines.append(
            "Use these as sensible defaults if the patient doesn't specify, but "
            "let anything they say now override them."
        )
        return "\n".join(lines)

    def get_booking_history(self, patient_name: str) -> List[Dict]:
        patient = self.get(patient_name)
        return patient.get("bookings", []) if patient else []

    def delete(self, patient_name: str):
        self.patients.pop(patient_name, None)

    def list_patients(self) -> List[str]:
        return list(self.patients.keys())

    def __len__(self):
        return len(self.patients)
