"""
Approval tokens: bound to (capability, args, principal, context).

A token is valid only for the exact action it was issued for. Any
mismatch — different args, different principal, different roles/tenant —
invalidates it. The AI cannot forge or reuse one because approval is not
part of its output channel.
"""

from __future__ import annotations

import pytest

from execgate.approval import (
    ApprovalToken,
    canonical_args_hash,
    context_hash,
    issue,
)
from execgate.context import ExecutionContext


def _ctx(principal: str = "alice", **kwargs) -> ExecutionContext:
    return ExecutionContext(principal=principal, **kwargs)


# ---------------------------------------------------------------------------
# canonical_args_hash
# ---------------------------------------------------------------------------


def test_args_hash_is_deterministic():
    assert canonical_args_hash({"a": 1, "b": 2}) == canonical_args_hash({"a": 1, "b": 2})


def test_args_hash_order_independent():
    assert canonical_args_hash({"a": 1, "b": 2}) == canonical_args_hash({"b": 2, "a": 1})


def test_args_hash_changes_with_values():
    assert canonical_args_hash({"a": 1}) != canonical_args_hash({"a": 2})


def test_args_hash_empty_dict():
    # Empty dict is a valid hash.
    h = canonical_args_hash({})
    assert isinstance(h, str) and len(h) == 64


# ---------------------------------------------------------------------------
# context_hash
# ---------------------------------------------------------------------------


def test_context_hash_deterministic():
    ctx = _ctx()
    assert context_hash(ctx) == context_hash(ctx)


def test_context_hash_changes_with_principal():
    assert context_hash(_ctx("alice")) != context_hash(_ctx("bob"))


def test_context_hash_changes_with_tenant():
    assert context_hash(_ctx(tenant="acme")) != context_hash(_ctx(tenant="other"))


def test_context_hash_role_order_independent():
    a = _ctx(roles=frozenset({"admin", "user"}))
    b = _ctx(roles=frozenset({"user", "admin"}))
    assert context_hash(a) == context_hash(b)


def test_context_hash_ignores_request_id():
    a = _ctx(request_id="req-1")
    b = _ctx(request_id="req-2")
    assert context_hash(a) == context_hash(b)


def test_context_hash_ignores_extra():
    a = _ctx(extra={"k": "v1"})
    b = _ctx(extra={"k": "v2"})
    assert context_hash(a) == context_hash(b)


# ---------------------------------------------------------------------------
# issue()
# ---------------------------------------------------------------------------


def test_issue_creates_valid_token():
    ctx = _ctx()
    token = issue(
        capability="refund",
        args={"order_id": 1, "amount": 5.0},
        context=ctx,
        issuer="human:alice",
    )
    assert isinstance(token, ApprovalToken)
    assert token.capability == "refund"
    assert token.principal == "alice"
    assert token.issuer == "human:alice"
    assert token.context_hash == context_hash(ctx)
    assert token.args_hash == canonical_args_hash({"order_id": 1, "amount": 5.0})


def test_issue_rejects_empty_capability():
    with pytest.raises(ValueError, match="capability"):
        issue(capability="", args={}, context=_ctx(), issuer="x")


def test_issue_rejects_non_dict_args():
    with pytest.raises(TypeError, match="args"):
        issue(capability="c", args=[], context=_ctx(), issuer="x")  # type: ignore[arg-type]


def test_issue_rejects_empty_issuer():
    with pytest.raises(ValueError, match="issuer"):
        issue(capability="c", args={}, context=_ctx(), issuer="")


# ---------------------------------------------------------------------------
# matches()
# ---------------------------------------------------------------------------


def test_matches_exact_action():
    ctx = _ctx()
    args = {"order_id": 1}
    token = issue(capability="refund", args=args, context=ctx, issuer="h:a")
    assert token.matches("refund", args, ctx)


def test_matches_arg_order_irrelevant():
    ctx = _ctx()
    token = issue(capability="refund", args={"a": 1, "b": 2}, context=ctx, issuer="h")
    assert token.matches("refund", {"b": 2, "a": 1}, ctx)


def test_mismatch_capability():
    ctx = _ctx()
    token = issue(capability="refund", args={}, context=ctx, issuer="h")
    assert not token.matches("other_cap", {}, ctx)


def test_mismatch_args():
    ctx = _ctx()
    token = issue(capability="refund", args={"amount": 5.0}, context=ctx, issuer="h")
    assert not token.matches("refund", {"amount": 999.0}, ctx)


def test_mismatch_principal():
    alice_ctx = _ctx("alice")
    bob_ctx = _ctx("bob")
    token = issue(capability="refund", args={}, context=alice_ctx, issuer="h")
    assert not token.matches("refund", {}, bob_ctx)


def test_mismatch_tenant():
    acme_ctx = _ctx(tenant="acme")
    other_ctx = _ctx(tenant="other")
    token = issue(capability="refund", args={}, context=acme_ctx, issuer="h")
    assert not token.matches("refund", {}, other_ctx)


def test_mismatch_roles():
    admin_ctx = _ctx(roles=frozenset({"admin"}))
    user_ctx = _ctx(roles=frozenset({"user"}))
    token = issue(capability="refund", args={}, context=admin_ctx, issuer="h")
    assert not token.matches("refund", {}, user_ctx)


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


def test_to_dict_contains_no_secrets():
    ctx = _ctx()
    token = issue(capability="refund", args={}, context=ctx, issuer="h")
    d = token.to_dict()
    assert set(d.keys()) == {
        "capability",
        "args_hash",
        "principal",
        "context_hash",
        "issued_at",
        "issuer",
    }
    # No plaintext args, no raw context.
    assert "args" not in d
    assert "context" not in d


# ---------------------------------------------------------------------------
# End-to-end: execute with a token
# ---------------------------------------------------------------------------


def test_execute_with_valid_token(logix):
    @logix.capability
    def refund(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    logix.require_approval(refund)

    ctx = logix.context(principal="alice")
    args = {"order_id": 1, "amount": 5.0}

    report = logix.verify({"call": "refund", "with": args}, context=ctx)
    assert report.ok
    token = issue(capability="refund", args=args, context=ctx, issuer="human:alice")

    result = logix.execute(report.verified_plan, context=ctx, approval=token)
    assert result.ok


def test_execute_with_wrong_args_token_rejected(logix):
    @logix.capability
    def refund(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    logix.require_approval(refund)

    ctx = logix.context(principal="alice")
    # Token bound to different args.
    token = issue(
        capability="refund",
        args={"order_id": 1, "amount": 999.0},
        context=ctx,
        issuer="human:alice",
    )

    report = logix.verify(
        {"call": "refund", "with": {"order_id": 1, "amount": 5.0}},
        context=ctx,
    )
    result = logix.execute(report.verified_plan, context=ctx, approval=token)
    assert not result.ok
    assert result.errors[0].code == "APPROVAL_REQUIRED"


def test_execute_with_wrong_principal_token_rejected(logix):
    @logix.capability
    def refund(order_id: int) -> dict[str, int]:
        return {"ok": 1}

    logix.require_approval(refund)

    alice_ctx = logix.context(principal="alice")
    bob_ctx = logix.context(principal="bob")
    token = issue(capability="refund", args={"order_id": 1}, context=alice_ctx, issuer="h")

    report = logix.verify({"call": "refund", "with": {"order_id": 1}}, context=bob_ctx)
    result = logix.execute(report.verified_plan, context=bob_ctx, approval=token)
    assert not result.ok
    assert result.errors[0].code == "APPROVAL_REQUIRED"
