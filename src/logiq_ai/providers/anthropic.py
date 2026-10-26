"""
Anthropic tool-use adapter.

``format_tools`` produces the ``tools`` parameter for
``client.messages.create(tools=...)``.

``parse_proposal`` accepts the full ``Message`` response object, the
``.content`` list, or a single ``tool_use`` block, and extracts the
first tool-use block as a neutral plan dict. Anthropic's ``input`` field
is already a dict — no JSON-string parsing needed.
"""

from __future__ import annotations

from typing import Any

from logiq_ai.base import AdapterError, ToolSpec


class AnthropicAdapter:
    """Adapter for the Anthropic Messages API tool-use format."""

    name = "anthropic"

    # -- format_tools ------------------------------------------------------

    def format_tools(self, specs: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
            }
            for spec in specs
        ]

    # -- parse_proposal ----------------------------------------------------

    def parse_proposal(self, raw: Any) -> dict[str, Any]:
        block = _extract_first_tool_use(raw)
        if block is None:
            raise AdapterError(
                "Anthropic response contains no tool_use block; expected "
                "content[] with type == 'tool_use'"
            )
        try:
            name = block["name"]
            tool_input = block.get("input", {})
        except (KeyError, TypeError) as e:
            raise AdapterError(f"malformed Anthropic tool_use block: missing name ({e})") from e

        if not isinstance(name, str) or not name:
            raise AdapterError(f"Anthropic tool_use block has invalid name: {name!r}")
        if not isinstance(tool_input, dict):
            raise AdapterError(
                f"Anthropic tool_use.input must be an object, got {type(tool_input).__name__}"
            )
        return {"call": name, "with": tool_input}


def _extract_first_tool_use(raw: Any) -> dict[str, Any] | None:
    # Full Message response
    if isinstance(raw, dict) and "content" in raw:
        return _extract_first_tool_use(raw.get("content") or [])

    # Content list
    if isinstance(raw, list):
        for block in raw:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return block
        return None

    # Single tool_use block
    if isinstance(raw, dict) and raw.get("type") == "tool_use":
        return raw

    return None
