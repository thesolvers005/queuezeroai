"""
QueueZero AI -- Claude provider.

Uses Anthropic's Claude with native tool calling. This is the recommended
provider for the actual demo/production run -- see ollama_provider.py for a
free local alternative to use while developing without spending API credits.
"""

import os

from anthropic import Anthropic
from dotenv import load_dotenv

from prompts import get_system_prompt
from tools import TOOL_DEFINITIONS, execute_tool

load_dotenv()

MODEL = "claude-sonnet-5"  # swap to claude-opus-4-8 for harder reasoning, claude-haiku-4-5-20251001 for speed/cost
MAX_TOOL_ROUNDS = 8  # safety cap so a confused loop can't run forever

# .strip() guards against trailing whitespace/newlines in a pasted env var;
# "" -> None so the SDK still raises a clear "missing key" error when unset.
client = Anthropic(api_key=(os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None)


def run_agent(user_message, conversation_history=None, on_step=None, extra_system=None):
    """
    Runs one turn of the agent loop.

    conversation_history: list of prior {"role": ..., "content": ...} messages,
        or None to start a fresh conversation.
    on_step: optional callback(step_dict) invoked after each tool call --
        wire this up to a UI to render the live "Reasoning Timeline".
    extra_system: optional string appended to the base system prompt for this
        turn only (used for patient-memory context and emergency-mode rules).

    Returns: {
        "reply": final text response,
        "steps": [{"tool": name, "input": {...}, "output": {...}}, ...],
        "history": updated conversation_history to pass into the next turn,
    }
    """
    messages = list(conversation_history) if conversation_history else []
    messages.append({"role": "user", "content": user_message})

    steps = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=get_system_prompt(extra_system),
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            final_text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            return {"reply": final_text, "steps": steps, "history": messages}

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            output = execute_tool(block.name, block.input)
            step = {"tool": block.name, "input": block.input, "output": output}
            steps.append(step)
            if on_step:
                on_step(step)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(output),
            })

        messages.append({"role": "user", "content": tool_results})

    return {
        "reply": "I wasn't able to finish reasoning through this in time -- could you narrow down your request?",
        "steps": steps,
        "history": messages,
    }
