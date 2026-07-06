"""
QueueZero AI -- Ollama (local) provider.

Uses a locally-running Ollama model with tool calling, so you can develop and
test the whole agent loop for free before spending Anthropic API credits.

Requires:
    - Ollama installed and running (`ollama serve`, usually automatic)
    - A tool-calling-capable model pulled, e.g. `ollama pull llama3.1`
    - pip install ollama

Set OLLAMA_MODEL in .env if you want to use a different pulled model.

Caveat: local models (especially smaller ones) are noticeably less reliable
than Claude at strict multi-step tool-calling and nuanced tradeoff reasoning.
Treat this provider as a free way to shake out plumbing bugs (wrong tool
names, bad schema, DB errors) before switching to Claude for the actual
reasoning-quality demo.
"""

import json
import os

import ollama
from dotenv import load_dotenv

from prompts import get_system_prompt
from tools import TOOL_DEFINITIONS, execute_tool, to_openai_tools

load_dotenv()

MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
MAX_TOOL_ROUNDS = 8

_OLLAMA_TOOLS = to_openai_tools(TOOL_DEFINITIONS)


def run_agent(user_message, conversation_history=None, on_step=None, extra_system=None):
    """Same interface/return shape as claude_provider.run_agent -- see there for details."""
    messages = list(conversation_history) if conversation_history else []
    # Ensure a system message is present as the first entry, rebuilt with any
    # per-request extra context (memory / emergency).
    system_prompt = get_system_prompt(extra_system)
    if messages and messages[0].get("role") == "system":
        messages[0] = {"role": "system", "content": system_prompt}
    else:
        messages.insert(0, {"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": user_message})

    steps = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = ollama.chat(model=MODEL, messages=messages, tools=_OLLAMA_TOOLS)
        message = response["message"]
        messages.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return {"reply": message.get("content", ""), "steps": steps, "history": messages}

        for call in tool_calls:
            name = call["function"]["name"]
            raw_args = call["function"]["arguments"]
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args

            output = execute_tool(name, args)
            step = {"tool": name, "input": args, "output": output}
            steps.append(step)
            if on_step:
                on_step(step)

            messages.append({"role": "tool", "content": str(output), "name": name})

    return {
        "reply": "I wasn't able to finish reasoning through this in time -- could you narrow down your request?",
        "steps": steps,
        "history": messages,
    }
