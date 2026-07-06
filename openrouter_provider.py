"""
QueueZero AI -- OpenRouter fallback provider.

Lets the agent run without Anthropic credits by routing through OpenRouter
(https://openrouter.ai) using the OpenAI Python SDK pointed at their
OpenAI-compatible endpoint. Strictly additive: claude_provider.py and
ollama_provider.py are untouched, and this module exposes the exact same
run_agent() interface and return shape, so the agent loop, memory and
emergency mode need zero changes.

Requires:
    - pip install openai
    - OPENROUTER_API_KEY in .env
    - FALLBACK_MODEL in .env (any tool-calling-capable OpenRouter model id)

Caveat: free/cheap OpenRouter models are noticeably less reliable than Claude
at strict tool calling — malformed tool-call JSON is common, so it's caught
and reported back to the model instead of crashing the booking flow.
"""

import json
import logging
import os

from dotenv import load_dotenv

from prompts import get_system_prompt
from tools import TOOL_DEFINITIONS, execute_tool, to_openai_tools

load_dotenv()

logger = logging.getLogger("queuezero.openrouter")

BASE_URL = "https://openrouter.ai/api/v1"
MODEL = os.environ.get("FALLBACK_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
MAX_TOOL_ROUNDS = 8

# Same shared Anthropic -> OpenAI schema conversion the Ollama provider uses;
# tool definitions live once in tools.py.
_OPENROUTER_TOOLS = to_openai_tools(TOOL_DEFINITIONS)

_TIMEOUT_REPLY = (
    "I wasn't able to finish reasoning through this in time -- could you "
    "narrow down your request?"
)


def _client():
    from openai import OpenAI

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def run_agent(user_message, conversation_history=None, on_step=None, extra_system=None):
    """Same interface/return shape as claude_provider.run_agent -- see there for details."""
    messages = list(conversation_history) if conversation_history else []
    # OpenAI-style APIs take the system prompt as the first message; rebuild it
    # each turn with any per-request extra context (memory / emergency).
    system_prompt = get_system_prompt(extra_system)
    if messages and messages[0].get("role") == "system":
        messages[0] = {"role": "system", "content": system_prompt}
    else:
        messages.insert(0, {"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": user_message})

    steps = []

    try:
        client = _client()
    except Exception as exc:
        logger.error("OpenRouter client init failed: %s", exc)
        return {
            "reply": f"The fallback model isn't configured ({exc}). Set OPENROUTER_API_KEY in .env.",
            "steps": steps,
            "history": messages,
        }

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=_OPENROUTER_TOOLS,
            )
            message = response.choices[0].message
        except Exception as exc:
            logger.error("OpenRouter call failed (model=%s): %s", MODEL, exc)
            return {
                "reply": (
                    "I hit a problem reaching the fallback model, so I couldn't finish "
                    "this booking. Please try again in a moment."
                ),
                "steps": steps,
                "history": messages,
            }

        # Store a plain dict (not the SDK object) so histories stay serializable
        # for session storage, exactly like the other providers' histories.
        messages.append(message.model_dump(exclude_none=True))

        tool_calls = message.tool_calls or []
        if not tool_calls:
            return {"reply": message.content or "", "steps": steps, "history": messages}

        for call in tool_calls:
            name = call.function.name
            raw_args = call.function.arguments
            try:
                args = json.loads(raw_args) if raw_args else {}
                if not isinstance(args, dict):
                    raise ValueError(f"expected a JSON object, got {type(args).__name__}")
            except (json.JSONDecodeError, ValueError) as exc:
                # Free models often emit malformed tool-call JSON. Feed the error
                # back as the tool result so the model can retry, never crash.
                logger.warning("Malformed tool args for %s: %r (%s)", name, raw_args, exc)
                args = {"_raw": raw_args}
                output = {"error": f"malformed tool arguments, send valid JSON: {exc}"}
            else:
                output = execute_tool(name, args)

            step = {"tool": name, "input": args, "output": output}
            steps.append(step)
            if on_step:
                on_step(step)

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": str(output),
            })

    return {"reply": _TIMEOUT_REPLY, "steps": steps, "history": messages}
