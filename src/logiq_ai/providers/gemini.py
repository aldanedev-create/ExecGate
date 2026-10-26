"""
Gemini function-calling adapter.

``format_tools`` produces the ``tools`` parameter for
``model.generate_content(tools=...)``.

``parse_proposal`` accepts the full response object, a candidate content
dict, a parts list, or a single part, and extracts the first
``functionCall`` as a neutral plan dict. Gemini's ``args`` field is
already a dict.
"""

from __future__ import annotations

from typing import Any

from logiq_ai.base import AdapterError, ToolSpec


class GeminiAdapter:
    """Adapter for the Gemini function-calling format."""

    name = "gemini"

    # -- format_tools ------------------------------------------------------

    def format_tools(self, specs: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.input_schema,
            }
            for spec in specs
        ]

    # -- parse_proposal ----------------------------------------------------

    def parse_proposal(self, raw: Any) -> dict[str, Any]:
        call = _extract_first_function_call(raw)
        if call is None:
            raise AdapterError(
                "Gemini response contains no functionCall; expected a "
                "part with a functionCall field"
            )
        try:
            name = call["name"]
            args = call.get("args", {})
        except (KeyError, TypeError) as e:
            raise AdapterError(f"malformed Gemini functionCall: missing name ({e})") from e

        if not isinstance(name, str) or not name:
            raise AdapterError(f"Gemini functionCall has invalid name: {name!r}")
        if not isinstance(args, dict):
            raise AdapterError(
                f"Gemini functionCall.args must be an object, got {type(args).__name__}"
            )
        return {"call": name, "with": args}


def _extract_first_function_call(raw: Any) -> dict[str, Any] | None:
    # Full response
    if isinstance(raw, dict) and "candidates" in raw:
        candidates = raw.get("candidates") or []
        if not candidates:
            return None
        content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
        return _extract_first_function_call(content)

    # Content dict
    if isinstance(raw, dict) and "parts" in raw:
        return _extract_first_function_call(raw.get("parts") or [])

    # Parts list
    if isinstance(raw, list):
        for part in raw:
            if isinstance(part, dict) and "functionCall" in part:
                fc = part["functionCall"]
                if isinstance(fc, dict):
                    return fc
        return None

    # Single part
    if isinstance(raw, dict) and "functionCall" in raw:
        fc = raw["functionCall"]
        return fc if isinstance(fc, dict) else None

    return None
