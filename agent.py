"""
QueueZero AI — agent entry point.

This is the ONLY file the rest of the app (CLI test, future FastAPI backend)
should import from. It picks which LLM actually powers the agent based on
LLM_PROVIDER in .env, without changing anything else.

    LLM_PROVIDER=anthropic   -> Claude, real credits required (default; use for the demo)
    LLM_PROVIDER=openrouter  -> OpenRouter fallback, no Anthropic credits needed
    LLM_PROVIDER=ollama      -> free, local, llama3.1 (good for dev)

Usage:
    from agent import run_agent
    result = run_agent("I need the earliest female cardiologist after 3pm, "
                        "within 10km, less than 20 min wait. My name is Priya.")
    print(result["reply"])
    for step in result["steps"]:
        print(step)
"""

import os

from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()

if PROVIDER == "anthropic":
    from claude_provider import run_agent
elif PROVIDER == "openrouter":
    from openrouter_provider import run_agent
elif PROVIDER == "ollama":
    from ollama_provider import run_agent
else:
    raise ValueError(
        f"Unknown LLM_PROVIDER '{PROVIDER}' — use 'anthropic', 'openrouter' or 'ollama'."
    )


if __name__ == "__main__":
    demo_request = (
        "I need the earliest available female cardiologist after 3 PM today. "
        "I don't want to travel more than 10 km from Mangalagiri, and I want "
        "under 20 minutes of waiting time. My name is Lakshmi Reddy."
    )
    print(f"Provider: {PROVIDER}")
    print(f"USER: {demo_request}\n")

    def print_step(step):
        print(f"  -> {step['tool']}({step['input']})")

    result = run_agent(demo_request, on_step=print_step)
    print(f"\nAGENT: {result['reply']}")
