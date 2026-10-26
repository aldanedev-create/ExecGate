"""
Local model adapter (Ollama, llama.cpp, vLLM in JSON mode).

Most local inference servers either (a) don't support native tool-calling
or (b) expose an OpenAI-compatible endpoint. This adapter covers case (a):
the model returns JSON text, and we parse it directly.

``format_tools`` returns the neutral catalog — the model needs to see
the JSON Schema, and neutral is a fine format for that.

``parse_proposal`` accepts a string (parse as JSON) or a response dict
with a ``response``, ``content``, ``message.content``, or ``text`` field
(the common shape across Ollama / llama.cpp / vLLM chat endpoints).

If your local server supports OpenAI-compatible tool calling, use
``get_adapter("openai")`` instead — the wire format is identical.

For providers with no native tool calling at all, use
``logiq_ai.prompt_json_mode.build(specs)`` to construct the system prompt
that asks the model to emit JSON.
"""

from __future__ import annotations

import json
from typing import Any

from logiq_ai.base import AdapterError, ToolSpec


class LocalAdapter:
    """Adapter for local models that return JSON text."""

    name = "local"

    # -- format_tools ------------------------------------------------------

    def format_tools(self, specs: list[ToolSpec]) -> list[dict[str, Any]]:
        return [spec.to_neutral_dict() for spec in specs]

    # -- parse_proposal ----------------------------------------------------

    def parse_proposal(self, raw: Any) -> dict[str, Any]:
        text = _extract_text(raw)
        if text is None:
            raise AdapterError(
                "local response contains no text; expected a JSON string or "
                "a response dict with a 'response', 'content', or 'text' field"
            )
        try:
            plan = json.loads(text)
        except json.JSONDecodeError as e:
            raise AdapterError(
                f"local model response is not valid JSON: {e}"
            ) from e
        if not isinstance(plan, dict):
            raise AdapterError(
                f"local model output must be a JSON object, got "
                f"{type(plan).__name__}"
            )
        return plan


def _extract_text(raw: Any) -> str | None:
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return None

    # Ollama: {"response": "..."}
    if isinstance(raw.get("response"), str):
        return raw["response"]

    # llama.cpp server: {"content": "..."}
    if isinstance(raw.get("content"), str):
        return raw["content"]

    # OpenAI-compatible chat: {"choices": [{"message": {"content": "..."}}]}
    if "choices" in raw:
        choices = raw.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]

    # vLLM simple: {"text": "..."}
    if isinstance(raw.get("text"), str):
        return raw["text"]

    return None