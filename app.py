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

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List

import bcrypt
import jwt
from fastapi import FastAPI, WebSocket, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

import db
import notifications
import tools
from memory import PatientMemory, ConversationHistory
from emergency import (
    should_trigger_emergency,
    mark_emergency_booking,
    get_emergency_system_prompt_injection,
    get_emergency_log,
)

load_dotenv()

app = FastAPI(title="QueueZero AI", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://queuezeroai.vercel.app"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Auth config (signup / login / JWT sessions)
# ------------------------------------------------------------------
JWT_SECRET = os.environ.get("JWT_SECRET", "").strip()
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 30

if not JWT_SECRET:
    # Fixed dev fallback (never a randomly-generated secret) so tokens survive
    # a restart/redeploy instead of being invalidated every time. This must
    # never be what's used in production -- set JWT_SECRET in the real env.
    JWT_SECRET = "dev-only-insecure-queuezero-jwt-secret-do-not-use-in-production"
    print(
        "[startup] WARNING: JWT_SECRET is not set. Falling back to a hardcoded "
        "DEV-ONLY secret -- all issued tokens are forgeable. Set JWT_SECRET in "
        "the environment before deploying."
    )

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def make_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


def _require_auth(authorization: Optional[str]) -> dict:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
    payload = decode_token(token) if token else None
    if not payload:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return payload


def _extract_user_id(authorization: Optional[str]) -> Optional[str]:
    """Returns the user_id from a Bearer token, or None if absent/invalid."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[len("Bearer "):].strip())
    return payload.get("sub") if payload else None


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


def is_mock_mode() -> bool:
    """True when the agent is running as the mock stand-in rather than the real
    provider -- either forced via USE_MOCK_AGENT or because the real provider
    failed to import. Single source of truth for the mock/live distinction."""
    return USE_MOCK_AGENT or _real_run_agent is None


def run_agent(*args, **kwargs):
    """Dispatch to the real provider unless mock is forced/needed."""
    if is_mock_mode():
        return _mock_run_agent(*args, **kwargs)
    return _real_run_agent(*args, **kwargs)


# ------------------------------------------------------------------
# App setup
# ------------------------------------------------------------------
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


class SignupRequest(BaseModel):
    email: str
    name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


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


def _send_confirmation_email(appointment: Optional[dict], patient_email: Optional[str]) -> dict:
    """Send the booking confirmation email for a completed appointment.

    Invoked by the request handlers immediately after a booking is detected in
    the agent's steps, so delivery is automatic and unconditional -- it never
    depends on the model choosing to call the send_notification tool. The
    recipient and appointment details are passed in per-request (no module-level
    state), so concurrent bookings cannot cross-contaminate each other. Never
    raises: send_confirmation_email reports any failure in its return value.

    Suppressed entirely in mock mode: a mock booking is a canned demo result,
    not a real reservation, so it must never trigger a real confirmation email.
    """
    if is_mock_mode():
        return {"sent": False, "error": "mock mode: confirmation email suppressed"}
    if not appointment:
        return {"sent": False, "error": "no appointment to confirm"}
    to_email = notifications.resolve_recipient(patient_email)
    if not to_email:
        return {"sent": False, "error": "no recipient email (form field or PATIENT_EMAIL env)"}
    return notifications.send_confirmation_email(
        to_email=to_email,
        doctor=appointment.get("doctor_name"),
        hospital=appointment.get("hospital_name"),
        date=appointment.get("appointment_date"),
        time=appointment.get("appointment_time"),
        est_wait=appointment.get("estimated_wait_mins"),
    )


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
async def book_appointment(req: BookRequest, authorization: Optional[str] = Header(None)):
    history = _get_session(req.session_id, prefix="sess")
    session_id = history.session_id

    user_id = _extract_user_id(authorization)
    if user_id:
        db.set_booking_user(user_id)

    is_emergency = should_trigger_emergency(req.user_message)
    extra_system = _build_extra_system(req.patient_name, is_emergency)

    try:
        result = run_agent(
            req.user_message,
            conversation_history=history.get_messages(),
            extra_system=extra_system,
        )
    finally:
        db.clear_booking_user()
    history.set_messages(result.get("history", []))

    appointment = extract_appointment_from_steps(result.get("steps", []))

    if appointment:
        # Fire the confirmation email automatically, using this request's own
        # recipient -- independent of whether the agent called send_notification.
        email_result = _send_confirmation_email(appointment, req.patient_email)
        if not email_result.get("sent"):
            print(f"[book] confirmation email not sent: {email_result.get('error')}")

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
# Streaming booking endpoint (SSE) -- reasoning-timeline foundation
# ------------------------------------------------------------------
def _run_agent_with_tool_events(emit, user_message, conversation_history, extra_system, user_id=None):
    """Runs on the executor thread: installs the per-thread emit hook that
    tools.execute_tool reads (see tools.py), so real tool-dispatch timing is
    observed without any change to claude_provider.py's tool-calling loop."""
    tools.set_emit_hook(emit)
    if user_id:
        db.set_booking_user(user_id)
    try:
        return run_agent(
            user_message,
            conversation_history=conversation_history,
            extra_system=extra_system,
        )
    finally:
        tools.clear_emit_hook()
        db.clear_booking_user()


@app.post("/api/chat/stream")
async def chat_stream(req: BookRequest, authorization: Optional[str] = Header(None)):
    """Streams each real agent reasoning/tool step as it happens (Server-Sent
    Events), for an animated reasoning timeline in the frontend. Purely
    additive -- POST /book is untouched and keeps working exactly as before.

    Frontend note: this is a POST endpoint, so the browser's native
    EventSource (GET-only) will NOT work against it. Consume it with
    fetch() + response.body.getReader() (ReadableStream) + TextDecoder
    instead.
    """
    history = _get_session(req.session_id, prefix="sess")
    session_id = history.session_id

    user_id = _extract_user_id(authorization)
    is_emergency = should_trigger_emergency(req.user_message)
    extra_system = _build_extra_system(req.patient_name, is_emergency)

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(event: dict):  # called from the worker thread
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def run_agent_task():
        try:
            result = await loop.run_in_executor(
                None,
                lambda: _run_agent_with_tool_events(
                    emit, req.user_message, history.get_messages(), extra_system, user_id
                ),
            )
            history.set_messages(result.get("history", []))
            appointment = extract_appointment_from_steps(result.get("steps", []))
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "final",
                    "session_id": session_id,
                    "reply": result.get("reply", ""),
                    "steps": result.get("steps", []),
                    "appointment": appointment,
                    "is_emergency": is_emergency,
                },
            )
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "error", "message": str(e)}
            )
        finally:
            # ALWAYS terminate the stream, even on failure
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "done"})

    async def gen():
        # id 0 marks the start of the loop itself, not a tool call -- emitted
        # directly here (already on the loop) rather than via tools.py.
        yield f"data: {json.dumps({'id': 0, 'step': '🧠 Understanding request', 'status': 'complete', 'details': ''})}\n\n"
        task = asyncio.create_task(run_agent_task())
        while True:
            event = await queue.get()
            if event.get("type") == "done":
                yield "data: [DONE]\n\n"
                break
            yield f"data: {json.dumps(event)}\n\n"
        await task

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------
# Emergency endpoint
# ------------------------------------------------------------------
@app.post("/emergency", response_model=BookResponse)
async def emergency_booking(req: EmergencyBookRequest):
    history = _get_session(req.session_id, prefix="emerg")
    session_id = history.session_id

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
        email_result = _send_confirmation_email(appointment, req.patient_email)
        if not email_result.get("sent"):
            print(f"[emergency] confirmation email not sent: {email_result.get('error')}")
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
# Auth (signup / login / verify) -- identity only, does not gate booking
# ------------------------------------------------------------------
@app.post("/auth/signup", status_code=201, response_model=AuthResponse)
async def auth_signup(req: SignupRequest):
    email = normalize_email(req.email)
    name = (req.name or "").strip()
    password = req.password or ""

    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if not name:
        raise HTTPException(status_code=400, detail="Please enter your name.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    client = db.get_client()
    existing = client.table("users").select("id").eq("email", email).limit(1).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="Email already registered")

    inserted = (
        client.table("users")
        .insert({"email": email, "password_hash": hash_password(password), "name": name})
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status_code=500, detail="Could not create account. Please try again.")

    user_row = inserted.data[0]
    token = make_token(user_row["id"], user_row["email"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user_row["id"], "email": user_row["email"], "name": user_row["name"]},
    }


@app.post("/auth/login", response_model=AuthResponse)
async def auth_login(req: LoginRequest):
    email = normalize_email(req.email)
    password = req.password or ""

    client = db.get_client()
    result = client.table("users").select("id, email, name, password_hash").eq("email", email).limit(1).execute()
    user_row = result.data[0] if result.data else None

    # Same message whether the email is unknown or the password is wrong, so a
    # caller can't use this endpoint to enumerate registered emails.
    if not user_row or not verify_password(password, user_row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = make_token(user_row["id"], user_row["email"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user_row["id"], "email": user_row["email"], "name": user_row["name"]},
    }


@app.post("/auth/verify")
async def auth_verify(authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()

    payload = decode_token(token) if token else None
    if not payload:
        return JSONResponse(status_code=401, content={"valid": False})

    client = db.get_client()
    result = (
        client.table("users").select("id, email, name").eq("id", payload.get("sub")).limit(1).execute()
    )
    if not result.data:
        return JSONResponse(status_code=401, content={"valid": False})

    user_row = result.data[0]
    return {
        "valid": True,
        "user": {"id": user_row["id"], "email": user_row["email"], "name": user_row["name"]},
    }


# ------------------------------------------------------------------
# User bookings
# ------------------------------------------------------------------
class CancelRequest(BaseModel):
    reason: str
    reason_detail: Optional[str] = None


@app.get("/api/bookings/mine")
async def my_bookings(authorization: Optional[str] = Header(None)):
    payload = _require_auth(authorization)
    return {"bookings": db.get_user_bookings(payload["sub"])}


@app.post("/api/bookings/{booking_id}/cancel")
async def cancel_my_booking(
    booking_id: str,
    req: CancelRequest,
    authorization: Optional[str] = Header(None),
):
    payload = _require_auth(authorization)
    result = db.cancel_booking(booking_id, payload["sub"], req.reason, req.reason_detail)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "mock" if is_mock_mode() else "live",
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
            patient_email = data.get("patient_email")
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
            if appointment:
                email_result = _send_confirmation_email(appointment, patient_email)
                if not email_result.get("sent"):
                    print(f"[ws] confirmation email not sent: {email_result.get('error')}")
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
