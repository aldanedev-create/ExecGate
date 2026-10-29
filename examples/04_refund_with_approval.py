"""
Refund with human approval — the Level 3 pattern.

Run:
    python examples/04_refund_with_approval.py

Demonstrates:
  - logix.verify() then logix.execute() separately
  - a human approval gate between verify and execute
  - approval tokens bound to (capability, args, principal, context)
  - approval does not bypass authorization

In a real application, `ask_human()` is a UI prompt, an email link, or
a CLI input. Here it's a stub that auto-approves. The important property
is that the AI has no path to the token — it is issued by application
code, bound to the exact action.
"""

from execgate import Logix, Allow, Deny
from execgate.approval import issue


def ask_human(capability: str, args: dict, principal: str) -> bool:
    """Stub for human approval. In real life: a UI prompt, email link, etc."""
    print(f"  [approval prompt] Approve {capability}({args}) for {principal}?")
    return True


def main() -> None:
    logix = Logix()

    ORDERS = {
        502: {"id": 502, "owner": "alice", "state": "delivered", "total": 50.0},
        777: {"id": 777, "owner": "bob", "state": "shipped", "total": 900.0},
    }
    REFUNDED: set[int] = set()

    @logix.capability(effects="read")
    def get_order(order_id: int) -> dict[str, float]:
        "Retrieve an order by its ID."
        order = ORDERS[order_id]
        return {"id": float(order["id"]), "total": order["total"]}

    @logix.capability(effects="write")
    def issue_refund(order_id: int, amount: float) -> dict[str, float]:
        "Issue a refund for an order."
        REFUNDED.add(order_id)
        return {"refunded": float(order_id), "amount": amount}

    logix.require_approval(issue_refund)
    logix.grounding(require_ref_for=["issue_refund.amount"])

    def refund_policy(args, ctx):
        order = ORDERS[args["order_id"]]
        if order["owner"] != ctx.principal:
            return Deny("NOT_OWNER", "caller does not own this order")
        if order["state"] != "delivered":
            return Deny("NOT_DELIVERED", "order is not refundable")
        return Allow()

    logix.authorize(issue_refund, check=refund_policy)

    # --- Happy path: alice refunds her order ---
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

    alice = logix.context(principal="alice")
    report = logix.verify(plan, context=alice)
    assert report.ok, report.errors

    if ask_human("issue_refund", {"order_id": 502, "amount": 50.0}, "alice"):
        token = issue(
            capability="issue_refund",
            args={"order_id": 502, "amount": 50.0},
            context=alice,
            issuer="human:alice",
        )
        result = logix.execute(report.verified_plan, context=alice, approval=token)
        print(f"\nHappy path: ok={result.ok}, 502 refunded={502 in REFUNDED}")

    # --- Approval does not bypass authorization ---
    # Alice tries to refund bob's order. A (bad) human approves it.
    # The invariant still denies.
    REFUNDED.clear()
    plan_bob = {
        "version": "1",
        "steps": [
            {"id": "o", "call": "get_order", "with": {"order_id": 777}},
            {
                "id": "r",
                "call": "issue_refund",
                "with": {"order_id": {"$ref": "o.id"}, "amount": {"$ref": "o.total"}},
            },
        ],
    }
    report = logix.verify(plan_bob, context=alice)
    assert report.ok

    # Issue a token anyway — a human approved (wrongly).
    token = issue(
        capability="issue_refund",
        args={"order_id": 777, "amount": 900.0},
        context=alice,
        issuer="human:alice",
    )
    result = logix.execute(report.verified_plan, context=alice, approval=token)
    print(f"\nApproval on wrong owner: ok={result.ok}, code={result.errors[0].code}")
    print(f"  777 refunded={777 in REFUNDED}")  # False
    print("  (Approval did not bypass the ownership invariant.)")


if __name__ == "__main__":
    main()
