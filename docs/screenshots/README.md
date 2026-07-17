# Screenshots needed

Capture these 4 and save them into this folder with the exact filenames below — the root `README.md` already references them by name, so they'll light up automatically once added.

1. **`timeline-live.png`** — *mandatory.* The reasoning timeline **mid-animation**, showing at least 2-3 tool-call steps already completed and one actively in progress. This is the centerpiece feature — capture it while a real (non-mock) booking request is running, not at rest.
2. **`booking-confirmed.png`** — The final booking confirmation card/state after a successful appointment, showing doctor, hospital, date/time.
3. **`chat-flow.png`** — The main chat interface with a user query typed/sent, showing the conversational booking flow.
4. **`auth-screen.png`** — The sign-in / sign-up screen.

## Notes

- PNG format, reasonable width (1200-1600px) — no need for full 4K.
- Crop out browser chrome / OS taskbar for a clean look.
- For `timeline-live.png` specifically: run a real query against `LLM_PROVIDER=anthropic` (or `openrouter`) rather than `USE_MOCK_AGENT=true`, so the timing/animation is genuine.
