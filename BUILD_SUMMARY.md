# QueueZero AI — Build Summary (Phases 3–6)

**Status:** Code complete, tested (import + logic + handler tests all pass).
Backend runs immediately in mock mode; switches to the real agent when keys are
set. No manual code-uncommenting required.

---

## What Was Built / Fixed

### Phase 3 — FastAPI Backend ✅  `app.py` (356 lines)

Endpoints:
- `POST /book` — main multi-turn booking conversation
- `POST /emergency` — priority override booking
- `POST /memory/save` — store patient preferences
- `GET /memory/{patient_name}` — retrieve patient record
- `GET /emergency/log` — audit log of emergency bookings
- `GET /health` — status + current mode (mock/live)
- `WS /ws/{session_id}` — optional live reasoning stream

Behavior:
- **Automatic mock fallback** — if `claude_provider` can't import (deps missing)
  or `USE_MOCK_AGENT=true`, a mock keeps the server + UI working with no API key.
- Sessions store the **canonical message list** returned by `run_agent` (fixes
  the earlier double-add of the user message).
- **Memory + emergency are actually injected** into the agent via
  `run_agent(extra_system=...)` (previously defined but unused).
- Appointment extraction matches the sanitized tool-output shape from `tools.py`.

### Phase 4 — React Chat UI ✅  `App.jsx` (257 lines)

- Chat interface (Vite + React + Tailwind).
- Reasoning timeline: one row per tool call, with ✓/error state.
- Green appointment confirmation card (no UUIDs shown).
- Emergency 🚨 banner.
- `API_URL` const with `VITE_API_URL` env override (no hardcoded URL).
- No HTML `<form>` (prevents accidental page reload on submit).

### Phase 5 — Memory Layer ✅  `memory.py` (175 lines)

- `ConversationHistory` — holds the canonical message list per session;
  `get_messages()` / `set_messages()` round-trip with `run_agent`.
- `PatientMemory` — stores preferences + booking history; `get_context_for_agent`
  formats them as a prompt injection (returns "" when nothing is stored, so it's
  safe to concatenate).

### Phase 6 — Emergency Mode ✅  `emergency.py` (96 lines)

- `should_trigger_emergency` — refined keyword scan (specific clinical phrases,
  fewer false positives).
- `get_emergency_system_prompt_injection` — the override rules that are now
  actually appended to the system prompt (book ASAP, any suitable doctor, use
  `emergency_book`, don't ask questions).
- `mark_emergency_booking` + `get_emergency_log` — audit trail.

### Supporting changes (required to make memory/emergency work)

- `prompts.py` (76 lines) — `get_system_prompt(extra_context)` appends
  per-request context; also added a language lock and an explicit
  "don't ask the user which doctor" autonomy rule.
- `claude_provider.py` (87 lines) — `run_agent(..., extra_system=None)` →
  `get_system_prompt(extra_system)`.
- `ollama_provider.py` (79 lines) — same `extra_system` param, so switching
  providers doesn't crash.
- `tools.py` (264 lines) — `_sanitize_output()` strips UUIDs/DB IDs before the
  model sees tool results (keeps `doctor_id` internally for the next call).

---

## How It Works Together

```
User → App.jsx → POST /book → app.py
  app.py detects emergency (emergency.py)
  app.py builds extra_system = patient memory (memory.py) + emergency rules (emergency.py)
  app.py calls run_agent(user_msg, conversation_history=session_msgs, extra_system=…)
     provider builds system prompt = base (prompts.py) + extra_system
     model calls tools; execute_tool sanitizes output (tools.py → db.py)
  app.py stores returned history back on the session
  app.py extracts the appointment, updates memory, logs emergencies
  app.py returns { reply, steps, appointment, is_emergency }
App.jsx renders bubbles + timeline + appointment card
```

---

## Test Results

Ran with stubbed `db`/`locations` and mock agent:

- ✅ imports: `prompts`, `memory`, `emergency`, `tools`, `app`
- ✅ sanitizer keeps `doctor_id`, drops unexpected columns; flattens `book_slot`
  date/time; no `patient_id` leak
- ✅ memory: unknown patient → "", known patient → context with prefs + last
  booking; booking history recorded
- ✅ conversation history set/get round-trip (no double-add)
- ✅ emergency: detects "chest pain", ignores "routine checkup"; injection text
  present; audit log records
- ✅ prompts: `extra_context` appended; language lock + autonomy rule present
- ✅ `_build_extra_system` merges memory + emergency
- ✅ `/book` handler runs under mock, sets emergency flag, no crash
- ✅ appointment extraction reads sanitized `book_slot`
- ✅ App.jsx: uses `API_URL`, null-safe fields, balanced braces, no `<form>`

---

## Line Count Summary

| Component | File | Lines |
|-----------|------|-------|
| Backend | app.py | 356 |
| UI | App.jsx | 257 |
| Tools + sanitizer | tools.py | 264 |
| Memory | memory.py | 175 |
| Emergency | emergency.py | 96 |
| System prompt | prompts.py | 76 |
| Claude provider | claude_provider.py | 87 |
| Ollama provider | ollama_provider.py | 79 |
| **Total (recreated)** | | **~1390** |

---

## One-Time Setup (~20 min)

1. **Supabase** — run `schema.sql` then `seed_data.sql`; confirm tables.
2. **.env** — Anthropic key + Supabase URL/key + `LLM_PROVIDER=anthropic`.
3. **Backend** — `pip install -r requirements.txt` → `uvicorn app:app --reload`.
4. **Frontend** — `npm create vite`, copy `App.jsx`, add Tailwind, `npm run dev`.

No code edits needed — mock/live is controlled by env + whether deps/keys exist.

---

## Testing Checklist

- [ ] `GET /health` shows `"mode":"live"` once keys + deps are in place
- [ ] Booking request returns a timeline + appointment card
- [ ] No UUIDs anywhere in the reply or card
- [ ] New row appears in Supabase `appointments`
- [ ] Emergency phrase ("chest pain") → 🚨 banner + `emergency_book` in timeline
- [ ] `/memory/save` then a booking recalls preferences without re-asking
- [ ] `/emergency/log` lists priority bookings

---

## Known Limitations (fine for submission)

1. In-memory sessions + patient memory (reset on restart).
2. No auth.
3. `send_notification` is a print stub.
4. No prompt caching (every call hits the API).
5. Ollama supported but less reliable than Claude for tool-calling.

---

## Next Features (after submission)

Patient login + booking-history dashboard; hospital-staff admin panel; real
SMS/email notifications; cancel/reschedule; WebSocket live timeline in the UI;
post-visit ratings; analytics.

See `INTEGRATION.md` for step-by-step setup, the full API reference, and
troubleshooting.
