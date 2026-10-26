"""
AI tool catalog: describe capabilities for an AI.

Run:
    python examples/02_ai_tool_catalog.py

Demonstrates:
  - logix.tools.describe()   — neutral ToolSpec list
  - logix.tools.format(...)  — provider-shaped catalog
  - the same schema for runtime validation and AI descriptions

Does not call a model. The catalog printed here is what you would send
to an AI provider's SDK. See examples/13_openai_end_to_end.py for a
real model call.
"""

import json

from logiq import Logix
from logiq_ai import get_adapter


def main() -> None:
    logix = Logix()

    @logix.capability(effects="read")
    def get_order(order_id: int) -> dict[str, float]:
        "Retrieve an order by its ID."
        return {"id": float(order_id), "total": 50.0}

    @logix.capability(effects="write", requires_approval=True)
    def issue_refund(order_id: int, amount: float) -> dict[str, float]:
        "Issue a refund for an order."
        return {"refunded": float(order_id), "amount": amount}

    # --- Neutral form (always available) ---
    print("=== tools.format('json') ===")
    print(json.dumps(logix.tools.format("json"), indent=2))

    # --- Provider-shaped forms (require logiq[ai]) ---
    print("\n=== tools.format('openai') ===")
    openai_adapter = get_adapter("openai")
    print(json.dumps(
        openai_adapter.format_tools(logix.tools.describe()), indent=2,
    )[:400] + "\n...")

    print("\n=== tools.format('anthropic') ===")
    anthropic_adapter = get_adapter("anthropic")
    print(json.dumps(
        anthropic_adapter.format_tools(logix.tools.describe()), indent=2,
    )[:400] + "\n...")

    # --- Unknown provider falls back to neutral ---
    print("\n=== tools.format('some-new-provider') ===")
    unknown = logix.tools.format("some-new-provider")
    print(f"Type: {type(unknown).__name__}")
    print(f"First entry name: {unknown[0]['name']}")
    print("(Falls back to neutral — never raises.)")

    # --- Same schema, two uses ---
    print("\n=== Same schema, two uses ===")
    catalog_schema = logix.tools.for_capability("issue_refund").input_schema
    verifier_schema = logix.schemas.for_capability("issue_refund").input
    print(f"Catalog schema == verifier schema: {catalog_schema == verifier_schema}")


if __name__ == "__main__":
    main()