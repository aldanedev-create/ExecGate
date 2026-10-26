"""
OpenAI tool-calling adapter.

``format_tools`` produces the ``tools`` parameter for
``client.chat.completions.create(tools=...)``.

``parse_proposal`` accepts the full chat completion response object, the
``.message`` dict, or the ``.tool_calls`` list, and extracts the first
tool call as a neutral plan dict. ``function.arguments`` is a JSON
string; it is parsed.
"""

from __future__ import annotations

import json
from typing import Any

from logiq_ai.base import AdapterError, ToolSpec


class OpenAIAdapter:
    """Adapter for the OpenAI Chat Completions tool-calling format."""

    name = "openai"

    # -- format_tools ------------------------------------------------------

    def format_tools(self, specs: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.input_schema,
                },
            }
            for spec in specs
        ]

    # -- parse_proposal ----------------------------------------------------

    def parse_proposal(self, raw: Any) -> dict[str, Any]:
        tool_call = _extract_first_tool_call(raw)
        if tool_call is None:
            raise AdapterError(
                "OpenAI response contains no tool call; expected a response "
                "with at least one choice[].message.tool_call"
            )
        try:
            name = tool_call["function"]["name"]
            arguments = tool_call["function"]["arguments"]
        except (KeyError, TypeError) as e:
            raise AdapterError(
                f"malformed OpenAI tool call: missing function.name or "
                f"function.arguments ({e})"
            ) from e

        if not isinstance(name, str) or not name:
            raise AdapterError(
                f"OpenAI tool call has invalid function.name: {name!r}"
            )

        if isinstance(arguments, str):
            try:
                parsed_args = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError as e:
                raise AdapterError(
                    f"OpenAI function.arguments is not valid JSON: {e}"
                ) from e
        elif isinstance(arguments, dict):
            parsed_args = arguments
        else:
            raise AdapterError(
                f"OpenAI function.arguments has unexpected type: "
                f"{type(arguments).__name__}"
            )

        if not isinstance(parsed_args, dict):
            raise AdapterError(
                f"OpenAI function.arguments must decode to an object, "
                f"got {type(parsed_args).__name__}"
            )

        return {"call": name, "with": parsed_args}


# ---------------------------------------------------------------------------
# Response shape walking
# ---------------------------------------------------------------------------

def _extract_first_tool_call(raw: Any) -> dict[str, Any] | None:
    """
    Accept any of the common wrappings and return the first tool call:

    - full response dict:     {"choices": [{"message": {"tool_calls": [...]}}]}
    - message dict:           {"tool_calls": [...]}
    - tool_calls list:        [{...}, ...]
    - single tool_call dict:  {"id": ..., "type": "function", "function": {...}}
    """
    if not isinstance(raw, (dict, list)):
        return None

    # Full response
    if isinstance(raw, dict) and "choices" in raw:
        choices = raw.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            return None
        return _extract_first_tool_call(message)

    # Message dict
    if isinstance(raw, dict) and "tool_calls" in raw:
        tool_calls = raw.get("tool_calls") or []
        return _extract_first_tool_call(tool_calls)

    # tool_calls list
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and "function" in item:
                return item
        return None

    # Single tool_call dict
    if isinstance(raw, dict) and "function" in raw:
        return raw

    return None