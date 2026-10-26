"""
Reference adapter — the ~30-line template.

Run:
    python examples/08_write_your_own_adapter.py

Demonstrates:
  - the entire ProviderAdapter protocol (two methods)
  - how to translate a fictional provider's catalog shape
  - how to parse a response into a neutral plan
  - end-to-end use: format -> propose -> parse -> run

This is the template to copy when adding a new provider adapter. The
conformance kit for a real adapter is in tests/adapters/contract.py;
this example shows the shape without requiring a full test suite.
"""

from typing import Any

from logiq import Logix
from logiq_ai.base import AdapterError, ToolSpec


class ExampleAdapter:
    """A minimal adapter for a fictional provider.

    Assumed request format:
        {"tools": [{"tool_name": "...", "tool_description": "...",
                    "args_schema": {...}}]}

    Assumed response format:
        {"chosen_tool": {"tool_name": "...", "tool_args": {...}}}
    """

    name = "example"

    def format_tools(self, specs: list[ToolSpec]) -> dict[str, Any]:
        """Neutral catalog -> fictional provider's tools shape."""
        return {
            "tools": [
                {
                    "tool_name": spec.name,
                    "tool_description": spec.description,
                    "args_schema": spec.input_schema,
                }
                for spec in specs
            ]
        }

    def parse_proposal(self, raw: Any) -> dict[str, Any]:
        """Fictional provider's response -> neutral plan dict."""
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


def main() -> None:
    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        "Add two integers."
        return a + b

    adapter = ExampleAdapter()

    # 1. Format the catalog.
    specs = logix.tools.describe()
    catalog = adapter.format_tools(specs)
    print("=== Catalog for the provider ===")
    print(catalog)

    # 2. Simulate a response from the provider's SDK.
    fake_response = {
        "chosen_tool": {
            "tool_name": "add",
            "tool_args": {"a": 10, "b": 20},
        }
    }
    print("\n=== Provider response ===")
    print(fake_response)

    # 3. Parse into a neutral plan.
    plan = adapter.parse_proposal(fake_response)
    print("\n=== Parsed plan ===")
    print(plan)

    # 4. Run through Logiq (full pipeline).
    result = logix.run(plan)
    print(f"\n=== Result ===\nok={result.ok}, value={result.value}")

    # 5. Show that errors are rejected cleanly.
    try:
        adapter.parse_proposal({"chosen_tool": {"tool_name": ""}})
    except AdapterError as e:
        print(f"\n=== Error case ===\nAdapterError: {e}")


if __name__ == "__main__":
    main()