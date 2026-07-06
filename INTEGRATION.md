# QueueZero AI — Integration Guide

Phases 3–6 are complete and tested (Backend, UI, Memory, Emergency). This guide
wires them together. **No code uncommenting needed** — the backend runs
immediately in mock mode and switches to the real agent once your keys are set.

---

## Architecture

```
User browser
   │
   ▼
React UI (App.jsx)  ──POST /book──►  FastAPI (app.py)
                                        │
                                        ├─ memory.py     (patient prefs + history)
                                        ├─ emergency.py  (keyword detect + priority rules)
                                        │
                                        └─ run_agent()  ──►  claude_provider.py
                                                                │  (or ollama_provider.py)
                                                                ├─ prompts.py   (system prompt + injected context)
                                                                ├─ tools.py     (tool schemas + sanitizer)
                                                                ├─ db.py        (Supabase)
                                                                └─ locations.py / distance.py
```

**Key idea:** memory context and emergency instructions are appended to the
system prompt per-request via `run_agent(extra_system=...)`. That's why
`prompts.py`, `claude_provider.py`, and `ollama_provider.py` all had to gain an
`extra_system` / `extra_context` parameter.

---

## File Checklist

Put ALL of these in one backend folder:

```
queuezero/
├── app.py               ← FastAPI server            (recreated)
├── memory.py            ← patient memory + history   (recreated)
├── emergency.py         ← emergency detection/rules  (recreated)
├── prompts.py           ← system prompt (extra_context)   (recreated)
├── claude_provider.py   ← Claude loop (extra_system)      (recreated)
├── ollama_provider.py   ← Ollama loop (extra_system)      (recreated)
├── agent.py             ← provider switch (unchanged from your version)
├── tools.py             ← tool schemas + ID sanitizer     (recreated earlier)
├── db.py                ← Supabase queries (your version)
├── locations.py         ← geocoding stub (your version)
├── distance.py          ← haversine (your version)
├── requirements.txt     ← from requirements_backend.txt
└── .env                 ← your keys
```

Frontend lives in a separate Vite project (see Step 2).

---

## Step 1 — Backend

### 1.1 Assemble the folder

```bash
mkdir queuezero && cd queuezero
# recreated files (from this session's outputs)
#   app.py memory.py emergency.py prompts.py claude_provider.py ollama_provider.py tools.py
# your existing files
#   agent.py db.py locations.py distance.py
cp /path/to/requirements_backend.txt requirements.txt
```

### 1.2 Create `.env`

```
ANTHROPIC_API_KEY=sk-ant-api03-YOUR-NEW-KEY
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
LLM_PROVIDER=anthropic

# Optional: force mock mode (UI works with no API/DB calls).
# Leave unset or "false" to use the real agent.
# USE_MOCK_AGENT=true
```

> Reminder: rotate the Google service-account key you pasted earlier if you
> haven't. And never hardcode keys in `.py` files — `.env` only.

### 1.3 Install + run

```bash
pip install -r requirements.txt
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### 1.4 Confirm mode

```bash
curl http://localhost:8000/health
```

- `"mode":"live"`  → real agent (keys loaded, claude_provider imported)
- `"mode":"mock"`  → mock (either `USE_MOCK_AGENT=true`, or deps/keys missing)

If you expected `live` but got `mock`, the startup log prints why (usually a
missing dependency for `claude_provider`).

---

## Step 2 — Frontend

### 2.1 Create the Vite project

```bash
npm create vite@latest queuezero-ui -- --template react
cd queuezero-ui
npm install
cp /path/to/App.jsx src/App.jsx
```

### 2.2 Tailwind (the UI uses Tailwind classes)

```bash
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

`tailwind.config.js`:
```javascript
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: { extend: {} },
  plugins: [],
}
```

`src/index.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

`src/main.jsx`:
```javascript
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

### 2.3 (Optional) point at a non-default backend

`App.jsx` reads `VITE_API_URL`, defaulting to `http://localhost:8000`. To
override, add `queuezero-ui/.env`:
```
VITE_API_URL=http://localhost:8000
```

### 2.4 Run

```bash
npm run dev
```

Open the printed URL (usually `http://localhost:5173`).

---

## Step 3 — Test End-to-End

With both servers running:

1. (Optional) enter your name in the "Your name" field.
2. Type:
   ```
   I need a female cardiologist after 3 PM today within 10 km of
   Mangalagiri, under 20 min wait. My name is Lakshmi Reddy.
   ```
3. Press Enter.

Expected (live mode):
- User + agent chat bubbles.
- "Agent thinking…" indicator.
- Reasoning timeline: `resolve_location → find_doctors → find_available_slots → book_slot → send_notification`.
- Green appointment card (doctor, hospital, date, time) — **no UUIDs anywhere**.
- Then verify a real row in Supabase → `appointments`.

In mock mode you'll get a single `[MOCK MODE]` reply and no timeline — that's
expected until keys are set.

---

## Step 4 — Memory (optional feature)

Save preferences:
```bash
curl -X POST http://localhost:8000/memory/save \
  -H "Content-Type: application/json" \
  -d '{"patient_name":"Lakshmi Reddy","preferred_specialization":"Cardiology","preferred_gender":"female"}'
```

Read them back:
```bash
curl "http://localhost:8000/memory/Lakshmi%20Reddy"
```

Now, if you send a `/book` request with `patient_name":"Lakshmi Reddy"`, the
backend injects those preferences into the system prompt, so the agent treats
them as defaults without asking again. (Injection point: `_build_extra_system`
in `app.py` → `PatientMemory.get_context_for_agent`.)

---

## Step 5 — Emergency mode (optional feature)

Two ways to trigger it:

**A) Natural language** — any emergency keyword in a normal `/book` message:
```
I have chest pain and need a cardiologist immediately!
```
The backend detects it, injects the emergency rules into the prompt (book ASAP,
any suitable doctor, use `emergency_book`, don't ask questions), and the UI
shows the 🚨 banner.

**B) Dedicated endpoint:**
```bash
curl -X POST http://localhost:8000/emergency \
  -H "Content-Type: application/json" \
  -d '{"patient_name":"Ravi Kumar","specialization":"Cardiology","reason":"chest pain"}'
```

Audit log of all emergency bookings:
```bash
curl http://localhost:8000/emergency/log
```

---

## API Reference

### POST /book
Request:
```json
{ "user_message": "...", "patient_name": "Lakshmi Reddy", "session_id": "sess_123" }
```
Response:
```json
{
  "session_id": "sess_123",
  "reply": "…reasoning summary…",
  "steps": [
    { "tool": "resolve_location", "input": {}, "output": {} },
    { "tool": "find_doctors", "input": {}, "output": [] },
    { "tool": "book_slot", "input": {}, "output": { "success": true } }
  ],
  "appointment": {
    "doctor_name": "Dr. Sneha Prasad",
    "hospital_name": "KIMS Hospitals",
    "appointment_date": "2026-07-05",
    "appointment_time": "16:00",
    "estimated_wait_mins": 5,
    "is_emergency": false
  },
  "is_emergency": false
}
```

### POST /emergency
Body: `{ patient_name, specialization, reason, session_id? }` — same response
shape, `is_emergency: true`, emergency rules forced into the prompt.

### POST /memory/save
Body: `{ patient_name, preferred_specialization?, preferred_gender?, preferred_hospital?, notes? }`

### GET /memory/{patient_name}
Returns the stored patient record (404 if unknown).

### GET /emergency/log
Returns `{ count, entries[] }` for a supervisor view.

### GET /health
Returns `{ status, mode, sessions_active, patients_known }`.

### WS /ws/{session_id}
Optional live stream. Send `{ "user_message": "...", "patient_name": "..." }`;
receive one `tool_call` event per tool, then a `final` event. POST /book is
enough for the MVP.

---

## Troubleshooting

- **`/health` says `mock` unexpectedly** → read the startup log line
  `[startup] Could not import claude_provider (...)`. Usually `pip install
  anthropic supabase` missing, or a syntax error in a provider file.
- **CORS error in browser** → your frontend origin isn't in `allow_origins`
  (`app.py`). Add it. Localhost 5173/3000 and 127.0.0.1:5173 are preset.
- **Agent errors on real call** → check `ANTHROPIC_API_KEY` + credits, and that
  Supabase `schema.sql` / `seed_data.sql` were run.
- **No appointment card** → look at the timeline. If `book_slot` never fired,
  the agent didn't reach booking (often no matching doctor, or missing patient
  name). If it fired with an error, the error shows in the timeline.
- **UUID visible to user** → shouldn't happen; the sanitizer in `tools.py`
  strips IDs. If you added a new tool, add it to `_sanitize_output`.

---

## Known Limitations (by design, fine for submission)

1. In-memory sessions + patient memory (lost on restart). Move to Supabase for
   production.
2. No auth — anyone can book. Add a simple login for production.
3. `send_notification` is a print stub — wire to SMS/email later.
4. FastAPI dispatches through `run_agent`, which honors `LLM_PROVIDER`. Ollama
   works but is less reliable than Claude at tool-calling.
5. No prompt caching yet — every call hits the API. Add caching to cut cost.

---

## What changed vs. the first backend draft

- Removed the "uncomment 2 lines" step — replaced with automatic mock fallback
  + `USE_MOCK_AGENT` toggle.
- Memory context and emergency rules are now actually injected into the agent
  (previously defined but unused).
- Fixed a double-add of the user message; sessions now store the canonical
  message list returned by `run_agent`.
- Providers and prompt gained `extra_system` / `extra_context`.
- App.jsx uses an `API_URL` const with `VITE_API_URL` override.
