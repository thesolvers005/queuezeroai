
```markdown
# QueueZero AI

Agentic hospital appointment booking system. Hackathon project — presentation is imminent.
Live: queuezeroai.vercel.app | Backend: Railway | DB: Supabase Postgres

## Architecture — read before changing anything

- `agent.py` — dispatches to claude_provider / openrouter_provider / ollama_provider
  via LLM_PROVIDER env var. All three share the signature:
  run_agent(user_message, conversation_history=None, on_step=None, extra_system=None)
- `tools.py` — 8 tools + dispatcher. The SSE emit hook lives here via threading.local.
  This is deliberate: it keeps streaming provider-agnostic.
- `app.py` — FastAPI. Routes: /api/chat/stream (SSE), /book, /emergency, /memory,
  /auth/*, /health
- `prompts.py` — reasoning policy is written in English, not code. MAX_TOOL_ROUNDS = 8
- `db.py` — the ONLY file that touches Supabase. Keep it that way; it's what makes a
  future UHI migration a one-file change.
- `notifications.py` — Resend email, fires from backend independent of the model.
- Frontend: `queuezero-ui/` (React + Vite)

## Hard rules

- DO NOT modify claude_provider.py, openrouter_provider.py, or ollama_provider.py.
- DO NOT change the SSE streaming architecture in tools.py. The animated reasoning
  timeline it feeds is the centerpiece feature for judge scoring. If a change would
  touch it, stop and ask.
- DO NOT alter the run_agent signature — three providers depend on it.
- Preserve existing API contracts. The deployed frontend depends on them.

## Environment

- Windows PowerShell. No head/grep/tail/curl-as-curl. Use Select-Object, Select-String.
- Backend runs on :8000, frontend on :5173
- Never commit .env. Update .env.example when adding a variable.

## Known gaps (context, not tasks)

- locations.py is a lookup stub, not real geocoding
- memory.py is in-memory, dies on restart
- No rate limiting, no RLS (service-role key = full DB access)
- No test suite (test.py / test_db.py are manual scripts)
- Emergency mode is keyword detection, not clinical triage — deliberate boundary
```

---