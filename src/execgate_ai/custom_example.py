"""
Reference adapter — ~30 lines, self-contained.

Use this as a template when adding a new provider. It shows the entire
contract: two methods, no SDK imports, no access to the trust side.

To register a real adapter, add an entry to ``_PROVIDERS`` in
``execgate_ai/registry.py``. This module is not registered; it exists only
as documentation and as a test fixture (``tests/adapters/test_custom_example.py``).
"""

from __future__ import annotations

from typing import Any

from execgate_ai.base import AdapterError, ToolSpec


class ExampleAdapter:
    """A minimal adapter for a fictional provider.

    Assumed request format::

        {"tools": [{"tool_name": "...", "tool_description": "...",
                    "args_schema": {...}}]}

    Assumed response format::

        {"chosen_tool": {"tool_name": "...", "tool_args": {...}}}
    """

    name = "example"

    def format_tools(self, specs: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "tool_name": spec.name,
                "tool_description": spec.description,
                "args_schema": spec.input_schema,
            }
            for spec in specs
        ]

    def parse_proposal(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict) or "chosen_tool" not in raw:
            raise AdapterError("expected a dict with a 'chosen_tool' key")
        chosen = raw["chosen_tool"]
        if not isinstance(chosen, dict):
            raise AdapterError("'chosen_tool' must be an object")
        name = chosen.get("tool_name")
        args = chosen.get("tool_args", {})
        if not isinstance(name, str) or not name:
            raise AdapterError("'chosen_tool.tool_name' must be a non-empty string")
        if not isinstance(args, dict):
            raise AdapterError("'chosen_tool.tool_args' must be an object")
        return {"call": name, "with": args}
