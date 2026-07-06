# QueueZero AI — Agent Core (Step 2)

This replaces `agent.py` and `gsheet.py` from your original Streamlit project.
`api.py` and `app.py` haven't been touched yet — that's Step 3 (backend) and
Step 4 (UI). For now this is a standalone, testable agent.

## Two LLM providers, one interface

Set `LLM_PROVIDER` in `.env` to switch — nothing else in the code needs to change:

- **`ollama`** (default) — free, runs locally via `llama3.1`, good for
  development while shaking out plumbing bugs without spending credits.
- **`anthropic`** — Claude via API, costs credits, noticeably stronger
  multi-step reasoning. Use this for your actual demo/recording.

`agent.py` is the single entry point — it just picks which provider module
(`claude_provider.py` or `ollama_provider.py`) to load based on that setting.
Both expose the exact same `run_agent()` interface.

## What changed vs. the old agent.py

| Old (`agent.py`)                         | New                                                        |
|-------------------------------------------|-------------------------------------------------------------|
| Hardcoded `if/else` slot logic             | An LLM decides what to search for and how to compare options |
| One department, fixed 3 slots              | Any specialization/gender/rating/distance/wait combination   |
| Google Sheets via `gsheet.py`              | Supabase via `db.py`                                          |
| Fixed reasoning strings                    | The model explains its actual tradeoffs in plain language     |

## Files

- **`locations.py`** — resolves a place name ("Mangalagiri") to lat/lon. Demo
  stand-in for a real geocoding API — same function signature either way.
- **`distance.py`** — haversine distance calculation.
- **`db.py`** — all Supabase queries (hospitals, doctors, schedules, booking,
  notifications). No LLM code here — pure data access, replaces `gsheet.py`.
- **`prompts.py`** — the shared system prompt (reasoning rules), used by both providers.
- **`tools.py`** — the tool schemas (`resolve_location`, `search_hospitals`,
  `find_doctors`, `find_available_slots`, `book_slot`, `emergency_book`,
  `find_patient_by_name`, `send_notification`), the dispatcher that runs the
  real function when a tool is called, and `to_openai_tools()` which converts
  the schema into the format Ollama/OpenAI-style models expect.
- **`claude_provider.py`** — the tool-calling loop using Anthropic's API.
- **`ollama_provider.py`** — the same loop using a local Ollama model.
- **`agent.py`** — picks a provider based on `LLM_PROVIDER` and re-exports its
  `run_agent()`. This is what everything else imports.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

For the Ollama path (default):
```bash
ollama pull llama3.1     # if you haven't already
ollama serve              # usually already running as a background service
```
Leave `LLM_PROVIDER=ollama` in `.env`.

For the Claude path, set `LLM_PROVIDER=anthropic` and fill in `ANTHROPIC_API_KEY`.

## Demo mode without Anthropic credits

Set `LLM_PROVIDER=openrouter` in `.env`. This routes the same agent loop
through [OpenRouter](https://openrouter.ai) via the OpenAI SDK
(`pip install openai`) — no Anthropic credits needed:

```
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...          # from https://openrouter.ai/keys
FALLBACK_MODEL=meta-llama/llama-3.3-70b-instruct:free
```

Tool definitions aren't duplicated — `openrouter_provider.py` reuses the same
`to_openai_tools()` conversion the Ollama provider uses, and returns the same
`{reply, steps, history}` shape, so the backend, memory, and emergency mode
work unchanged. Free models are shakier at tool calling than Claude; malformed
tool-call JSON is caught and fed back to the model instead of crashing.

Either way, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are always required
(Step 1's schema + seed data must already be applied).

## Email confirmations (Resend)

After a successful booking, the agent's `send_notification` step also sends a
real confirmation email (an appointment-slip layout matching the UI's green
card) via [Resend](https://resend.com). This only happens in live mode — in
mock mode (`USE_MOCK_AGENT=true`) the notification stays a print stub.

Setup:

1. `pip install resend` (already in `requirements.txt`).
2. Create an API key at <https://resend.com/api-keys> and set `RESEND_API_KEY`
   in `.env`.
3. **Verify your sending domain**: in the Resend dashboard go to
   *Domains → Add domain*, enter the domain you'll send from, then add the
   DKIM/SPF DNS records Resend shows you at your DNS provider and wait for the
   status to turn **Verified**. Set `FROM_EMAIL` to an address on that domain,
   e.g. `QueueZero <bookings@yourdomain.com>`. Without a verified domain you
   can only use Resend's sandbox sender `onboarding@resend.dev`, which is fine
   for testing but only delivers to your own Resend account email.
4. The recipient comes from the booking form's email field; if the field is
   left empty, the `PATIENT_EMAIL` env var is used as a demo fallback.

Email failures never block a booking — `notifications.py` catches everything,
logs a warning, and reports `{"sent": false, "error": ...}` in the tool result.

## Try it

```bash
python3 agent.py
```

This runs a canned request through the full loop and prints each tool call
plus the final reasoned answer — e.g. it will call `resolve_location` for
"Mangalagiri", then `find_doctors` with the gender/specialization/distance
filters, then `find_available_slots`, then `book_slot`, then
`send_notification`, and finally explain which doctor it picked and why.

For your own test, open a `python3` shell:

```python
from agent import run_agent
result = run_agent("I need a dermatologist tomorrow morning, my name is Ravi Kumar.")
print(result["reply"])
for step in result["steps"]:
    print(step)
```

`result["history"]` is the running message list — pass it back into
`run_agent()` as `conversation_history` for multi-turn conversations (e.g. the
agent asks a clarifying question, the user replies, you continue the same
thread instead of starting over).

## A note on local model quality

`llama3.1` (and most local models) are meaningfully less reliable than Claude
at strict multi-step tool calling — expect occasional malformed tool calls,
weaker tradeoff reasoning (e.g. it might just pick the highest-rated doctor
without genuinely weighing distance/wait), or shallower final explanations.
That's a model capability gap, not a bug in this code. Use Ollama to confirm
the plumbing works (right tools called, DB queries succeed, booking completes),
then switch to `LLM_PROVIDER=anthropic` once you're ready to show the real
reasoning quality — that's what the "AI agent, not rule-based automation"
pitch in your original spec actually depends on.

## Design notes

- **Tool granularity matches your original spec** (`search_hospitals`,
  `find_doctors`, `find_available_slots`, `book_slot`, `send_notification`) —
  the model chains them itself; nothing here decides the order in advance.
- **Reasoning is in the system prompt, not hardcoded logic** — the tradeoff
  guidance (constraints first, then weigh rating/distance/wait together,
  relax the least important constraint if nothing fits) mirrors the Doctor
  A vs. Doctor B example in your spec, but the model applies it to whatever
  data actually comes back, not a scripted scenario.
- **`emergency_book`** is a separate tool rather than a flag on `book_slot`,
  so the system prompt can tell the model exactly when it's allowed to use it
  (only for genuinely urgent situations) instead of leaving that judgment
  call to slip through unnoticed.
- **`MAX_TOOL_ROUNDS = 8`** is a safety cap — if the agent gets stuck
  looping between tool calls without reaching an answer, it stops and asks
  the user to narrow the request instead of hanging forever.

## Next step

Step 3: wrap `run_agent()` in a FastAPI backend (replacing `api.py`) with a
proper chat endpoint, so the frontend can stream tool-call progress to the
UI's "Reasoning Timeline" as each step completes — that's what the `on_step`
callback in `run_agent()` is already set up for.

