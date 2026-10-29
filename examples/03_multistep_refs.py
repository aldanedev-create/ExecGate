"""
Multi-step plans with $ref.

Run:
    python examples/03_multistep_refs.py

Demonstrates:
  - a two-step plan where step 2 references step 1's output
  - forward references rejected at parse time
  - type-mismatched references rejected at verify time
  - grounding (require_ref_for) preventing literal amounts

This is the canonical refund workflow. Every value the second step uses
comes from the first step's validated output — the model cannot type a
refund amount.
"""

from execgate import Logix, Deny


def main() -> None:
    logix = Logix()

    ORDERS = {
        502: {"id": 502, "total": 50.0, "state": "delivered"},
    }

    @logix.capability(effects="read")
    def get_order(order_id: int) -> dict[str, float]:
        "Retrieve an order by its ID."
        order = ORDERS[order_id]
        return {"id": float(order["id"]), "total": order["total"]}

    @logix.capability(effects="write")
    def issue_refund(order_id: float, amount: float) -> dict[str, float]:
        "Issue a refund."
        return {"refunded": order_id, "amount": amount}

    # Grounding: the amount must come from a prior step.
    logix.grounding(require_ref_for=["issue_refund.amount"])

    # --- Success: grounded multi-step plan ---
    plan = {
        "version": "1",
        "steps": [
            {"id": "o", "call": "get_order", "with": {"order_id": 502}},
            {
                "id": "r",
                "call": "issue_refund",
                "with": {"order_id": {"$ref": "o.id"}, "amount": {"$ref": "o.total"}},
            },
        ],
    }
    result = logix.run(plan)
    print(f"Grounded multi-step: ok={result.ok}")
    print(f"Value: {result.value}")

    # --- Failure: literal amount rejected by grounding ---
    bad_plan = {
        "version": "1",
        "steps": [
            {"id": "o", "call": "get_order", "with": {"order_id": 502}},
            {
                "id": "r",
                "call": "issue_refund",
                "with": {"order_id": {"$ref": "o.id"}, "amount": 9999.0},
            },  # ← literal
        ],
    }
    result = logix.run(bad_plan)
    print(f"\nLiteral amount: code={result.errors[0].code}")
    print(f"  message: {result.errors[0].message}")

    # --- Failure: forward reference rejected at parse ---
    forward_plan = {
        "version": "1",
        "steps": [
            {
                "id": "r",
                "call": "issue_refund",
                "with": {"order_id": {"$ref": "o.id"}, "amount": {"$ref": "o.total"}},
            },
            {"id": "o", "call": "get_order", "with": {"order_id": 502}},
        ],
    }
    result = logix.run(forward_plan)
    print(f"\nForward reference: code={result.errors[0].code}")

    # --- Failure: type-mismatched reference rejected at verify ---
    @logix.capability
    def get_count() -> dict[str, int]:
        "Return an integer count."
        return {"count": 3}

    mismatch_plan = {
        "version": "1",
        "steps": [
            {"id": "c", "call": "get_count", "with": {}},
            {
                "id": "r",
                "call": "issue_refund",
                "with": {
                    "order_id": {"$ref": "c.count"},  # int → float
                    "amount": 5.0,
                },
            },  # literal (would fail grounding too)
        ],
    }
    result = logix.run(mismatch_plan)
    print(f"\nint → float reference: code={result.errors[0].code}")


if __name__ == "__main__":
    main()
