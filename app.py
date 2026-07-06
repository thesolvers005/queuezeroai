"""
QueueZero FastAPI Backend -- connects the React frontend to the booking agent.

Endpoints:
- POST /book             main conversation (multi-step, multi-turn booking)
- POST /emergency        priority override booking
- POST /memory/save      store patient preferences
- GET  /memory/{name}    retrieve patient preferences
- GET  /emergency/log    audit log of emergency bookings
- GET  /health           status
- WS   /ws/{session_id}  optional live reasoning stream (basic)

Agent wiring:
  This module imports run_agent from claude_provider. If that import fails
  (deps not installed yet) OR the env var USE_MOCK_AGENT=true is set, it falls
  back to a mock so the server still boots and the UI is demoable without an
  API key. To run the real agent, install requirements + set your keys in .env
  and leave USE_MOCK_AGENT unset (or "false").
"""

import os
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

import notifications
from memory import PatientMemory, ConversationHistory
from emergency import (
    should_trigger_emergency,
    mark_emergency_booking,
    get_emergency_system_prompt_injection,
    get_emergency_log,
)

load_dotenv()

# Create app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://queuezeroai.vercel.app", "http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Agent wiring (real provider with graceful mock fallback)
# ------------------------------------------------------------------
USE_MOCK_AGENT = os.environ.get("USE_MOCK_AGENT", "false").lower() == "true"

try:
    # agent.py picks the provider from LLM_PROVIDER (anthropic default,
    # openrouter fallback, ollama local) — same run_agent interface either way.
    from agent import run_agent as _real_run_agent
except Exception as exc:  # deps missing / import-time error -> fall back to mock
    print(f"[startup] Could not import agent provider ({exc}); using mock agent.")
    _real_run_agent = None


def _mock_run_agent(user_message, conversation_history=None, on_step=None, extra_system=None):
    """Stand-in that mimics run_agent's return shape so the UI works with no API.

    Simulates a full booking round (location -> doctors -> slots -> book) with
    the same sanitized step/output shapes tools.py produces, so the reasoning
    timeline and appointment card render exactly like a live run.
    """
    import time

    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": user_message})

    emergency = "EMERGENCY" in (extra_system or "") or "EMERGENCY" in user_message.upper()
    book_tool = "emergency_book" if emergency else "book_slot"

    steps = [
        {
            "tool": "resolve_location",
            "input": {"place_name": "Mangalagiri"},
            "output": {"place_name": "Mangalagiri", "lat": 16.43, "lon": 80.55},
        },
        {
            "tool": "find_doctors",
            "input": {"specialization": "Dermatology", "max_distance_km": 10},
            "output": {"count": 3, "doctors": [
                {"doctor_name": "Dr. Ananya Sharma", "rating": 4.8, "distance_km": 3.2},
                {"doctor_name": "Dr. Priya Verma", "rating": 4.9, "distance_km": 11.0},
                {"doctor_name": "Dr. Kavya Rao", "rating": 4.5, "distance_km": 5.1},
            ]},
        },
        {
            "tool": "find_available_slots",
            "input": {"doctor_name": "Dr. Ananya Sharma", "period": "morning"},
            "output": {"slots": ["09:30", "10:15", "11:00"], "estimated_wait_mins": 10},
        },
        {
            "tool": book_tool,
            "input": {"doctor_name": "Dr. Ananya Sharma", "slot": "09:30"},
            "output": {
                "success": True,
                "doctor_name": "Dr. Ananya Sharma",
                "hospital_name": "Sunrise Skin Clinic",
                "appointment_date": "2026-07-07",
                "appointment_time": "09:30",
                "estimated_wait_mins": 10,
            },
        },
        {
            "tool": "send_notification",
            "input": {"message": "Appointment confirmed for 09:30"},
            "output": {"sent": True},
        },
    ]
    for step in steps:
        if on_step:
            on_step(step)
        time.sleep(0.4)  # let the UI's "working" state be visible

    reply = (
        "[MOCK MODE] I compared 3 dermatologists near Mangalagiri. Dr. Priya Verma "
        "has the highest rating (4.9) but is 11 km away; Dr. Ananya Sharma is rated "
        "4.8, only 3.2 km away with a 10 minute wait — the best overall tradeoff. "
        "Booked tomorrow at 9:30 AM at Sunrise Skin Clinic."
    )
    if emergency:
        reply = (
            "[MOCK MODE] This is urgent — I booked the nearest suitable doctor "
            "immediately with priority: Dr. Ananya Sharma at Sunrise Skin Clinic. "
            "Go now, they are expecting you."
        )
    messages.append({"role": "assistant", "content": reply})
    return {"reply": reply, "steps": steps, "history": messages}


def run_agent(*args, **kwargs):
    """Dispatch to the real provider unless mock is forced/needed."""
    if USE_MOCK_AGENT or _real_run_agent is None:
        return _mock_run_agent(*args, **kwargs)
    return _real_run_agent(*args, **kwargs)


# ------------------------------------------------------------------
# App setup
# ------------------------------------------------------------------
app = FastAPI(title="QueueZero AI", version="1.0")

app.add_middleware(
    CORSMiddleware,
    # local dev: the Vite dev server may land on any port
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS: dict = {}  # {session_id: ConversationHistory}
PATIENT_MEMORY = PatientMemory()


# ------------------------------------------------------------------
# Models
# ------------------------------------------------------------------
class BookRequest(BaseModel):
    user_message: str
    patient_name: Optional[str] = None
    patient_email: Optional[str] = None  # falls back to PATIENT_EMAIL env var
    session_id: Optional[str] = None


class BookResponse(BaseModel):
    session_id: str
    reply: str
    steps: List[dict]
    appointment: Optional[dict] = None
    is_emergency: bool = False


class PatientPreference(BaseModel):
    patient_name: str
    preferred_specialization: Optional[str] = None
    preferred_gender: Optional[str] = None
    preferred_hospital: Optional[str] = None
    notes: Optional[str] = None


class EmergencyBookRequest(BaseModel):
    patient_name: str
    specialization: str
    reason: str  # "chest pain", "allergic reaction", etc.
    patient_email: Optional[str] = None  # falls back to PATIENT_EMAIL env var
    session_id: Optional[str] = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _get_session(session_id: Optional[str], prefix: str = "sess") -> ConversationHistory:
    sid = session_id or f"{prefix}_{datetime.now().timestamp()}"
    if sid not in SESSIONS:
        SESSIONS[sid] = ConversationHistory(sid)
    return SESSIONS[sid]


def _build_extra_system(patient_name: Optional[str], is_emergency: bool) -> Optional[str]:
    """Assemble per-request system-prompt additions (memory + emergency)."""
    parts = []
    if patient_name:
        ctx = PATIENT_MEMORY.get_context_for_agent(patient_name)
        if ctx:
            parts.append(ctx)
    if is_emergency:
        parts.append(get_emergency_system_prompt_injection())
    return "\n\n".join(parts) if parts else None


def extract_appointment_from_steps(steps: List[dict]) -> Optional[dict]:
    """
    Find a successful book_slot / emergency_book in the tool steps and return
    its user-facing appointment details. Matches the sanitized tool output
    shape from tools.py (flat keys, no nested 'appointment').
    """
    for step in steps or []:
        tool_name = step.get("tool", "")
        output = step.get("output", {})
        if not isinstance(output, dict):
            continue
        if tool_name in ("book_slot", "emergency_book") and output.get("success"):
            return {
                "doctor_name": output.get("doctor_name"),
                "hospital_name": output.get("hospital_name"),
                "appointment_date": output.get("appointment_date"),
                "appointment_time": output.get("appointment_time"),
                "estimated_wait_mins": output.get("estimated_wait_mins"),
                "is_emergency": tool_name == "emergency_book",
            }
    return None


# ------------------------------------------------------------------
# Main booking endpoint
# ------------------------------------------------------------------
@app.post("/book", response_model=BookResponse)
async def book_appointment(req: BookRequest):
    history = _get_session(req.session_id, prefix="sess")
    session_id = history.session_id

    # Recipient for the confirmation email; None clears any previous override
    # so a request without an email falls back to the PATIENT_EMAIL env var.
    notifications.set_recipient(req.patient_email)

    is_emergency = should_trigger_emergency(req.user_message)
    extra_system = _build_extra_system(req.patient_name, is_emergency)

    # run_agent appends the user message and its own tool/assistant messages,
    # then returns the full updated history -- so we pass the stored list in and
    # store the returned list back. We do NOT add the user message ourselves.
    result = run_agent(
        req.user_message,
        conversation_history=history.get_messages(),
        extra_system=extra_system,
    )
    history.set_messages(result.get("history", []))

    appointment = extract_appointment_from_steps(result.get("steps", []))

    if appointment and req.patient_name:
        PATIENT_MEMORY.save(patient_name=req.patient_name, last_booking=appointment)

    if is_emergency and appointment:
        mark_emergency_booking(appointment, req.user_message)

    return BookResponse(
        session_id=session_id,
        reply=result.get("reply", ""),
        steps=result.get("steps", []),
        appointment=appointment,
        is_emergency=is_emergency,
    )


# ------------------------------------------------------------------
# Emergency endpoint
# ------------------------------------------------------------------
@app.post("/emergency", response_model=BookResponse)
async def emergency_booking(req: EmergencyBookRequest):
    history = _get_session(req.session_id, prefix="emerg")
    session_id = history.session_id

    notifications.set_recipient(req.patient_email)

    emergency_message = (
        f"EMERGENCY: {req.reason}. Patient name: {req.patient_name}. "
        f"I need an urgent {req.specialization} appointment now."
    )

    # Force emergency-mode instructions (+ any known patient context) into the
    # system prompt for this turn.
    extra_system = _build_extra_system(req.patient_name, is_emergency=True)

    result = run_agent(
        emergency_message,
        conversation_history=history.get_messages(),
        extra_system=extra_system,
    )
    history.set_messages(result.get("history", []))

    appointment = extract_appointment_from_steps(result.get("steps", []))
    if appointment:
        PATIENT_MEMORY.save(patient_name=req.patient_name, last_booking=appointment)
        mark_emergency_booking(appointment, req.reason)

    return BookResponse(
        session_id=session_id,
        reply=result.get("reply", ""),
        steps=result.get("steps", []),
        appointment=appointment,
        is_emergency=True,
    )


# ------------------------------------------------------------------
# Memory endpoints
# ------------------------------------------------------------------
@app.post("/memory/save")
async def save_patient_memory(pref: PatientPreference):
    PATIENT_MEMORY.save(
        patient_name=pref.patient_name,
        specialization=pref.preferred_specialization,
        gender=pref.preferred_gender,
        hospital=pref.preferred_hospital,
        notes=pref.notes,
    )
    return {"success": True, "patient_name": pref.patient_name}


@app.get("/memory/{patient_name}")
async def get_patient_memory(patient_name: str):
    prefs = PATIENT_MEMORY.get(patient_name)
    if not prefs:
        raise HTTPException(status_code=404, detail="Patient not found")
    return prefs


# ------------------------------------------------------------------
# Emergency audit log
# ------------------------------------------------------------------
@app.get("/emergency/log")
async def emergency_log():
    return {"count": len(get_emergency_log()), "entries": get_emergency_log()}


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "mock" if (USE_MOCK_AGENT or _real_run_agent is None) else "live",
        "sessions_active": len(SESSIONS),
        "patients_known": len(PATIENT_MEMORY),
    }


# ------------------------------------------------------------------
# WebSocket (optional live reasoning stream)
# ------------------------------------------------------------------
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    Optional live stream. On each user message it runs the agent and pushes one
    event per tool call (via run_agent's on_step callback) followed by the final
    reply. POST /book is enough for the MVP; use this only if you want a live
    'thinking' timeline in the UI.
    """
    await websocket.accept()
    history = _get_session(session_id, prefix="ws")
    try:
        while True:
            data = await websocket.receive_json()
            user_message = data.get("user_message", "")
            patient_name = data.get("patient_name")
            is_emergency = should_trigger_emergency(user_message)
            extra_system = _build_extra_system(patient_name, is_emergency)

            steps_buffer = []

            def _on_step(step):
                steps_buffer.append(step)

            result = run_agent(
                user_message,
                conversation_history=history.get_messages(),
                on_step=_on_step,
                extra_system=extra_system,
            )
            history.set_messages(result.get("history", []))

            for step in steps_buffer:
                await websocket.send_json({"type": "tool_call", "step": _jsonable(step)})

            appointment = extract_appointment_from_steps(result.get("steps", []))
            await websocket.send_json({
                "type": "final",
                "reply": result.get("reply", ""),
                "appointment": appointment,
                "is_emergency": is_emergency,
            })
    except Exception as e:  # includes client disconnect
        print(f"[ws] closed: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


def _jsonable(step: dict) -> dict:
    """Best-effort make a tool step JSON-serializable for the WS stream."""
    return {
        "tool": step.get("tool"),
        "input": step.get("input"),
        "output": step.get("output") if isinstance(step.get("output"), (dict, list, str, int, float, bool, type(None))) else str(step.get("output")),
    }


if __name__ == "__main__":
    import uvicorn
    # Note: --reload only works from the CLI (`uvicorn app:app --reload`),
    # not when passing the app object here.
    uvicorn.run(app, host="0.0.0.0", port=8000)
