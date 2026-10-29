"""
Pydantic models as capability schemas.

Run:
    python examples/05_pydantic_models.py

Requires:
    pip install "logiq[pydantic]"

Demonstrates:
  - a Pydantic BaseModel used as a capability schema
  - field constraints (Field(ge=0)) enforced
  - Pydantic validation errors translated to Logiq errors
  - $ref into a model-typed output
  - HandlerMode.MODEL vs HandlerMode.VALUES
"""

import json

from pydantic import BaseModel, Field

from execgate import Logix
from execgate_pydantic import HandlerMode, set_handler_mode


class CreateOrder(BaseModel):
    product_id: int = Field(ge=0)
    quantity: int = Field(ge=1, le=100)


class Order(BaseModel):
    id: int
    status: str
    total: float


def main() -> None:
    logix = Logix()

    @logix.capability(effects="write")
    def prepare_order(order: CreateOrder) -> Order:
        "Prepare an order for review."
        return Order(id=1, status="pending", total=order.quantity * 10.0)

    @logix.capability(effects="read")
    def get_order(order_id: int) -> Order:
        "Retrieve an order by ID."
        return Order(id=order_id, status="delivered", total=50.0)

    @logix.capability(effects="write")
    def refund(order_id: int, amount: float) -> dict[str, float]:
        "Issue a refund."
        return {"refunded": float(order_id), "amount": amount}

    # --- The catalog shows the model's JSON Schema ---
    print("=== Inferred schema for prepare_order ===")
    spec = logix.tools.for_capability("prepare_order")
    print(json.dumps(spec.input_schema, indent=2))

    # --- Valid call: handler receives a CreateOrder instance (MODEL mode) ---
    set_handler_mode(HandlerMode.MODEL)

    @logix.capability
    def inspect_model(order: CreateOrder) -> dict[str, str]:
        "Report what the handler received."
        return {
            "type": type(order).__name__,
            "quantity": str(order.quantity),
        }

    result = logix.run(
        {
            "call": "inspect_model",
            "with": {"order": {"product_id": 1, "quantity": 5}},
        }
    )
    print(f"\nMODEL mode: handler got {result.value}")

    # --- VALUES mode: handler receives a dict ---
    set_handler_mode(HandlerMode.VALUES)

    @logix.capability
    def inspect_values(order: CreateOrder) -> dict[str, str]:
        "Report what the handler received."
        return {
            "type": type(order).__name__,
            "quantity": str(order["quantity"]),  # dict access
        }

    result = logix.run(
        {
            "call": "inspect_values",
            "with": {"order": {"product_id": 1, "quantity": 5}},
        }
    )
    print(f"VALUES mode: handler got {result.value}")

    set_handler_mode(HandlerMode.MODEL)  # restore

    # --- Constraint violation: quantity > le=100 ---
    result = logix.run(
        {
            "call": "prepare_order",
            "with": {"order": {"product_id": 1, "quantity": 500}},
        }
    )
    print(f"\nConstraint violation: code={result.errors[0].code}")
    print(f"  message: {result.errors[0].message}")

    # --- $ref into a model's output field ---
    plan = {
        "version": "1",
        "steps": [
            {"id": "o", "call": "get_order", "with": {"order_id": 1}},
            {
                "id": "r",
                "call": "refund",
                "with": {"order_id": {"$ref": "o.id"}, "amount": {"$ref": "o.total"}},
            },
        ],
    }
    result = logix.run(plan)
    print(f"\n$ref into Order fields: ok={result.ok}, value={result.value}")


if __name__ == "__main__":
    main()
