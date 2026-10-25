"""
Schema validity is not authorization.

A plan that passes every schema check can still be rejected by a live
authorization check, and a plan that passes authorization in one context
can fail in another. The two layers are independent.

This is the counterpart to ``test_unknown_capability_never_invokes``:
unknown names are blocked, but so are valid names under the wrong
conditions.
"""

from __future__ import annotations

import pytest

from logix import Allow, Deny


@pytest.mark.security
def test_valid_schema_does_not_grant_authorization(logix):
    invoked = []

    @logix.capability
    def refund(order_id: int, amount: float) -> dict[str, int]:
        invoked.append(1)
        return {"ok": 1}

    # Schema-valid args, but authorization says no.
    logix.authorize(refund, check=lambda args, ctx: Deny("FORBIDDEN", "no"))

    result = logix.run({
        "call": "refund",
        "with": {"order_id": 1, "amount": 5.0},
    })
    assert not result.ok
    assert result.errors[0].code == "POLICY_REJECTED"
    assert invoked == []


@pytest.mark.security
def test_authorization_is_context_dependent(logix):
    invoked = []

    @logix.capability
    def read_account(account_id: int) -> dict[str, int]:
        invoked.append(account_id)
        return {"id": account_id}

    # Only alice can read.
    def owner_only(args, ctx):
        if ctx.principal == "alice":
            return Allow()
        return Deny("NOT_OWNER", "not your account")

    logix.authorize(read_account, check=owner_only)

    alice = logix.context(principal="alice")
    bob = logix.context(principal="bob")

    # Alice: allowed.
    r_alice = logix.run(
        {"call": "read_account", "with": {"account_id": 1}}, context=alice,
    )
    assert r_alice.ok
    assert invoked == [1]

    # Bob: same schema-valid plan, rejected.
    r_bob = logix.run(
        {"call": "read_account", "with": {"account_id": 1}}, context=bob,
    )
    assert not r_bob.ok
    assert r_bob.errors[0].code == "POLICY_REJECTED"
    assert invoked == [1]  # bob's call did not invoke


@pytest.mark.security
def test_authorization_runs_after_schema_not_instead_of(logix):
    """Both layers run. A schema-invalid input is caught by the schema
    check, not the authorize check (which would see malformed args)."""
    invoked = []

    @logix.capability
    def refund(order_id: int, amount: float) -> dict[str, int]:
        invoked.append(1)
        return {"ok": 1}

    logix.authorize(refund, check=lambda args, ctx: Allow())  # always allow

    # Schema-invalid input: rejected by schema, authorize never runs
    # (and even if it did, it would return Allow, so we know the outcome
    # is due to schema).
    result = logix.run({
        "call": "refund",
        "with": {"order_id": "not-an-int", "amount": 5.0},
    })
    assert not result.ok
    assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"
    assert invoked == []


@pytest.mark.security
def test_authorization_cannot_be_short_circuited_by_schema(logix):
    """Passing every schema constraint does not skip the invariant."""
    from typing import Annotated
    from logix.schemas import Gt, Le

    invoked = []

    @logix.capability
    def refund(
        amount: Annotated[float, Gt(0), Le(100)],
    ) -> dict[str, int]:
        invoked.append(amount)
        return {"ok": 1}

    logix.authorize(refund, check=lambda args, ctx: Deny("BLOCKED", "no"))

    # Amount 50 satisfies Gt(0) and Le(100); authorize still blocks.
    result = logix.run({"call": "refund", "with": {"amount": 50.0}})
    assert not result.ok
    assert result.errors[0].code == "POLICY_REJECTED"
    assert invoked == []