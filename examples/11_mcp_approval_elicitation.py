"""
Approval gate between MCP client and Logiq execution.

Run:
    python examples/11_mcp_approval_elicitation.py

Requires:
    pip install "logiq[mcp]"

Demonstrates:
  - a capability with requires_approval=True
  - the MCP server path returns APPROVAL_REQUIRED (see docs/mcp.md §3.1)
  - the workaround: split verify from execute, insert a human approval
    in the application, then call execute() with the token

The limitation: MCP tools/call has no channel for an ApprovalToken, so
a capability with requires_approval=True is unreachable over MCP server
mode. This example shows the recommended workaround: expose the
sensitive capability through direct application code, not through
LogixMCPServer.

The "human" in this example is a stub that auto-approves. In a real app
it's a UI prompt or a separate approval service.
"""

from logiq import Logix, Allow
from logiq.approval import issue


def ask_human(capability: str, args: dict, principal: str) -> bool:
    """Stub for human approval."""
    print(f"  [approval prompt] Approve {capability}({args}) for {principal}?")
    return True


def main() -> None:
    logix = Logix()

    REFUNDED: set[int] = set()

    @logix.capability(effects="write")
    def issue_refund(order_id: int, amount: float) -> dict[str, float]:
        "Issue a refund."
        REFUNDED.add(order_id)
        return {"refunded": float(order_id), "amount": amount}

    logix.require_approval(issue_refund)

    # --- The limitation: MCP server mode cannot carry approvals ---
    print("=== The limitation (MCP server mode) ===")
    print(
        "A capability with requires_approval=True cannot be reached over "
        "MCP server mode in 0.1.0 — every call returns APPROVAL_REQUIRED.\n"
        "See docs/mcp.md §3.1.\n"
    )

    # Demonstrate the failing path directly.
    plan = {"call": "issue_refund", "with": {"order_id": 502, "amount": 50.0}}
    result = logix.run(plan)
    print(f"Direct run without token: code={result.errors[0].code}")
    print(f"  (Same result any MCP client would see.)\n")

    # --- The workaround: application-side approval gate ---
    print("=== The workaround: application-side approval ===")
    ctx = logix.context(principal="alice")

    report = logix.verify(plan, context=ctx)
    print(f"1. verify: ok={report.ok}")

    if ask_human("issue_refund", {"order_id": 502, "amount": 50.0}, "alice"):
        token = issue(
            capability="issue_refund",
            args={"order_id": 502, "amount": 50.0},
            context=ctx,
            issuer="human:alice",
        )
        print(f"2. token issued by application code")

        result = logix.execute(report.verified_plan, context=ctx, approval=token)
        print(f"3. execute: ok={result.ok}, 502 refunded={502 in REFUNDED}")

    print(
        "\nIn an MCP deployment, the application layer (your webhook, UI, "
        "or approval service) owns step 2. The MCP client calls the "
        "application's endpoint, which does verify + approve + execute."
    )


if __name__ == "__main__":
    main()