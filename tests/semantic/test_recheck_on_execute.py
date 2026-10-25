"""
The recheck window.

``recheck_step`` is called by the executor before each handler. It runs
context refresh (optional), invariants, approval, and idempotency in
order and returns a ``RecheckResult`` indicating whether to proceed,
replay, deny, or escalate to approval.
"""

from __future__ import annotations

import pytest

from logix import Allow, Deny, RequireApproval
from logix.approval import issue
from logix.context import ExecutionContext
from logix.semantic import (
    InMemoryIdempotencyStore,
    RecheckStatus,
    recheck_step,
)
from logix.semantic.invariants import InvariantRegistry


def _ctx(principal: str = "alice") -> ExecutionContext:
    return ExecutionContext(principal=principal)


def _empty_invariants() -> InvariantRegistry:
    return InvariantRegistry()


# ---------------------------------------------------------------------------
# Baseline: all clear
# ---------------------------------------------------------------------------

def test_all_clear_proceeds():
    result = recheck_step(
        capability="cap",
        args={"x": 1},
        context=_ctx(),
        invariants=_empty_invariants(),
    )
    assert result.status is RecheckStatus.PROCEED
    assert result.error is None


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def test_deny_returns_deny():
    reg = InvariantRegistry()
    reg.add("cap", lambda args, ctx: Deny("REASON", "not allowed"))
    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=reg,
    )
    assert result.status is RecheckStatus.DENY
    assert result.error.code == "POLICY_REJECTED"


def test_allow_falls_through():
    reg = InvariantRegistry()
    reg.add("cap", lambda args, ctx: Allow())
    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=reg,
    )
    assert result.status is RecheckStatus.PROCEED


def test_invariant_exception_returns_deny():
    def crash(args, ctx):
        raise RuntimeError("db down")

    reg = InvariantRegistry()
    reg.add("cap", crash)
    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=reg,
    )
    assert result.status is RecheckStatus.DENY
    assert result.error.code == "AUTHORIZATION_FAILED"


def test_require_approval_from_invariant_falls_through_to_approval():
    """RequireApproval from an invariant sets the approval flag and falls
    through to the approval check. No token → APPROVAL_REQUIRED."""
    reg = InvariantRegistry()
    reg.add("cap", lambda args, ctx: RequireApproval("needs review"))
    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=reg,
        # approval_required_flag not set, but the invariant sets it.
    )
    assert result.status is RecheckStatus.APPROVAL_REQUIRED
    assert result.error.code == "APPROVAL_REQUIRED"


def test_require_approval_with_valid_token_proceeds():
    reg = InvariantRegistry()
    reg.add("cap", lambda args, ctx: RequireApproval("needs review"))

    ctx = _ctx()
    args = {"x": 1}
    token = issue(capability="cap", args=args, context=ctx, issuer="human:alice")

    result = recheck_step(
        capability="cap", args=args, context=ctx, invariants=reg,
        approval_token=token,
    )
    assert result.status is RecheckStatus.PROCEED


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------

def test_approval_required_no_token():
    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=_empty_invariants(),
        approval_required_flag=True,
    )
    assert result.status is RecheckStatus.APPROVAL_REQUIRED
    assert result.error.code == "APPROVAL_REQUIRED"


def test_approval_required_valid_token():
    ctx = _ctx()
    args = {"x": 1}
    token = issue(capability="cap", args=args, context=ctx, issuer="human:alice")

    result = recheck_step(
        capability="cap", args=args, context=ctx, invariants=_empty_invariants(),
        approval_required_flag=True, approval_token=token,
    )
    assert result.status is RecheckStatus.PROCEED


def test_approval_required_mismatched_token():
    ctx = _ctx()
    wrong_args = {"x": 999}
    token = issue(capability="cap", args=wrong_args, context=ctx, issuer="human:alice")

    result = recheck_step(
        capability="cap", args={"x": 1}, context=ctx, invariants=_empty_invariants(),
        approval_required_flag=True, approval_token=token,
    )
    assert result.status is RecheckStatus.APPROVAL_REQUIRED


def test_approval_not_required_token_ignored():
    """When approval is not required, a token is not consumed."""
    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=_empty_invariants(),
        approval_required_flag=False,
        approval_token=None,
    )
    assert result.status is RecheckStatus.PROCEED


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_idempotency_fresh_reserves():
    store = InMemoryIdempotencyStore()
    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=_empty_invariants(),
        idempotency_store=store,
        idempotency_key="k1",
        idempotency_args_hash="h1",
    )
    assert result.status is RecheckStatus.PROCEED


def test_idempotency_replay_after_commit():
    store = InMemoryIdempotencyStore()
    store.check_and_reserve("k1", "h1")
    store.commit("k1", {"cached": "value"})

    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=_empty_invariants(),
        idempotency_store=store,
        idempotency_key="k1",
        idempotency_args_hash="h1",
    )
    assert result.status is RecheckStatus.REPLAY
    assert result.cached_value == {"cached": "value"}


def test_idempotency_conflict_on_different_hash():
    store = InMemoryIdempotencyStore()
    store.check_and_reserve("k1", "h1")
    store.commit("k1", "old result")

    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=_empty_invariants(),
        idempotency_store=store,
        idempotency_key="k1",
        idempotency_args_hash="h2",
    )
    assert result.status is RecheckStatus.DENY
    assert result.error.code == "IDEMPOTENCY_CONFLICT"


def test_idempotency_conflict_in_flight():
    store = InMemoryIdempotencyStore()
    store.check_and_reserve("k1", "h1")  # reserved but not committed

    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=_empty_invariants(),
        idempotency_store=store,
        idempotency_key="k1",
        idempotency_args_hash="h1",
    )
    assert result.status is RecheckStatus.DENY
    assert result.error.code == "IDEMPOTENCY_CONFLICT"


def test_idempotency_key_without_hash_denies():
    store = InMemoryIdempotencyStore()
    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=_empty_invariants(),
        idempotency_store=store,
        idempotency_key="k1",
        # idempotency_args_hash not provided
    )
    assert result.status is RecheckStatus.DENY
    assert result.error.code == "AUTHORIZATION_FAILED"
    assert "args_hash" in result.error.message


def test_idempotency_store_none_skips():
    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=_empty_invariants(),
        idempotency_store=None,
        idempotency_key="k1",
        idempotency_args_hash="h1",
    )
    assert result.status is RecheckStatus.PROCEED


# ---------------------------------------------------------------------------
# Context refresher
# ---------------------------------------------------------------------------

def test_context_refresh_same_principal_proceeds():
    def refresher():
        return _ctx("alice")  # same as current

    result = recheck_step(
        capability="cap", args={}, context=_ctx("alice"), invariants=_empty_invariants(),
        context_refresher=refresher,
    )
    assert result.status is RecheckStatus.PROCEED


def test_context_refresh_changed_principal_denies():
    def refresher():
        return _ctx("bob")

    result = recheck_step(
        capability="cap", args={}, context=_ctx("alice"), invariants=_empty_invariants(),
        context_refresher=refresher,
    )
    assert result.status is RecheckStatus.DENY
    assert result.error.code == "AUTHORIZATION_FAILED"
    assert "principal changed" in result.error.message


def test_context_refresh_exception_denies():
    def refresher():
        raise RuntimeError("session expired")

    result = recheck_step(
        capability="cap", args={}, context=_ctx(), invariants=_empty_invariants(),
        context_refresher=refresher,
    )
    assert result.status is RecheckStatus.DENY
    assert result.error.code == "AUTHORIZATION_FAILED"