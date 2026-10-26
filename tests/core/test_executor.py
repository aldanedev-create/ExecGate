"""
The executor.

Acceptance: only a ``VerifiedPlan``; every step runs the recheck window;
output is validated; invariants, approval, idempotency, and audit hooks
all fire. These are integration tests — the verifier runs first because
the executor is only meaningful with a real ``VerifiedPlan``.
"""

from __future__ import annotations

import pytest

from execgate import Allow, Deny
from execgate.approval import issue

# ---------------------------------------------------------------------------
# Structural guarantee: execute() rejects anything but a VerifiedPlan
# ---------------------------------------------------------------------------


def test_execute_rejects_dict(logix):
    with pytest.raises(TypeError, match="VerifiedPlan"):
        logix.execute({"verified": True})  # type: ignore[arg-type]


def test_execute_rejects_none(logix):
    with pytest.raises(TypeError, match="VerifiedPlan"):
        logix.execute(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Result shape: single-call vs multi-step
# ---------------------------------------------------------------------------


def test_single_call_returns_value(logix):
    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    result = logix.run({"call": "add", "with": {"a": 1, "b": 2}})
    assert result.ok
    assert result.value == 3


def test_multi_step_returns_dict(logix):
    @logix.capability
    def one() -> int:
        return 1

    @logix.capability
    def two(x: int) -> int:
        return x + 1

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "a", "call": "one", "with": {}},
                {"id": "b", "call": "two", "with": {"x": {"$ref": "a"}}},
            ],
        }
    )
    assert result.ok
    assert result.value == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# Handler never invoked when verify fails
# ---------------------------------------------------------------------------


def test_handler_not_invoked_on_unknown_capability(logix):
    invoked: list[int] = []

    @logix.capability
    def add(a: int, b: int) -> int:
        invoked.append(1)
        return a + b

    result = logix.run({"call": "does_not_exist", "with": {}})
    assert not result.ok
    assert result.errors[0].code == "UNKNOWN_CAPABILITY"
    assert invoked == []


def test_handler_not_invoked_on_schema_failure(logix):
    invoked: list[int] = []

    @logix.capability
    def add(a: int, b: int) -> int:
        invoked.append(1)
        return a + b

    result = logix.run({"call": "add", "with": {"a": "not-an-int", "b": 2}})
    assert not result.ok
    assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"
    assert invoked == []


def test_handler_not_invoked_when_invariant_denies(logix):
    invoked: list[int] = []

    @logix.capability
    def refund(order_id: int) -> dict[str, int]:
        invoked.append(1)
        return {"ok": 1}

    logix.authorize(refund, check=lambda args, ctx: Deny("ORDER_NOT_DELIVERED", "x"))
    result = logix.run({"call": "refund", "with": {"order_id": 1}})
    assert not result.ok
    assert result.errors[0].code == "POLICY_REJECTED"
    assert invoked == []


# ---------------------------------------------------------------------------
# Handler invocation and output validation
# ---------------------------------------------------------------------------


def test_handler_exception_produces_handler_failed(logix):
    @logix.capability
    def fail(x: int) -> int:
        raise ValueError("boom")

    result = logix.run({"call": "fail", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "HANDLER_FAILED"


def test_output_validation_failure_produces_output_validation_failed(logix):
    @logix.capability
    def bad(x: int) -> int:
        return "not an int"  # type: ignore[return-value]

    result = logix.run({"call": "bad", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "OUTPUT_VALIDATION_FAILED"


def test_output_validation_skipped_when_no_schema(logix):
    @logix.capability
    def anything(x: int):  # unannotated return
        return "any value"

    result = logix.run({"call": "anything", "with": {"x": 1}})
    assert result.ok
    assert result.value == "any value"


# ---------------------------------------------------------------------------
# Invariants (live-state checks)
# ---------------------------------------------------------------------------


def test_invariant_allow_proceeds(logix):
    @logix.capability
    def read(x: int) -> int:
        return x

    logix.authorize(read, check=lambda args, ctx: Allow())
    result = logix.run({"call": "read", "with": {"x": 1}})
    assert result.ok


def test_invariant_crash_denies(logix):
    @logix.capability
    def read(x: int) -> int:
        return x

    def crash(args, ctx):
        raise RuntimeError("db down")

    logix.authorize(read, check=crash)
    result = logix.run({"call": "read", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "AUTHORIZATION_FAILED"


def test_invariant_returns_garbage_denies(logix):
    @logix.capability
    def read(x: int) -> int:
        return x

    logix.authorize(read, check=lambda args, ctx: "not a decision")  # type: ignore[arg-type]
    result = logix.run({"call": "read", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "AUTHORIZATION_FAILED"


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


def test_approval_required_no_token(logix):
    @logix.capability
    def refund(order_id: int) -> dict[str, int]:
        return {"ok": 1}

    logix.require_approval(refund)
    result = logix.run({"call": "refund", "with": {"order_id": 1}})
    assert not result.ok
    assert result.errors[0].code == "APPROVAL_REQUIRED"


def test_approval_with_matching_token_proceeds(logix):
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


def test_approval_with_mismatched_args_rejected(logix):
    @logix.capability
    def refund(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    logix.require_approval(refund)
    ctx = logix.context(principal="alice")
    wrong_args = {"order_id": 1, "amount": 999.0}

    report = logix.verify(
        {"call": "refund", "with": {"order_id": 1, "amount": 5.0}},
        context=ctx,
    )
    token = issue(capability="refund", args=wrong_args, context=ctx, issuer="human:alice")

    result = logix.execute(report.verified_plan, context=ctx, approval=token)
    assert not result.ok
    assert result.errors[0].code == "APPROVAL_REQUIRED"


def test_approval_with_mismatched_principal_rejected(logix):
    @logix.capability
    def refund(order_id: int) -> dict[str, int]:
        return {"ok": 1}

    logix.require_approval(refund)
    alice_ctx = logix.context(principal="alice")
    bob_ctx = logix.context(principal="bob")
    args = {"order_id": 1}

    report = logix.verify({"call": "refund", "with": args}, context=bob_ctx)
    token = issue(capability="refund", args=args, context=alice_ctx, issuer="human:alice")

    result = logix.execute(report.verified_plan, context=bob_ctx, approval=token)
    assert not result.ok
    assert result.errors[0].code == "APPROVAL_REQUIRED"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotent_capability_replays(logix):
    calls: list[int] = []

    @logix.capability(idempotent=True)
    def charge(order_id: int, amount: float) -> dict[str, int]:
        calls.append(order_id)
        return {"ok": 1}

    r1 = logix.run({"call": "charge", "with": {"order_id": 1, "amount": 5.0}})
    r2 = logix.run({"call": "charge", "with": {"order_id": 1, "amount": 5.0}})

    assert r1.ok and r2.ok
    assert r1.value == r2.value
    assert len(calls) == 1  # handler invoked once


def test_idempotent_different_args_both_call(logix):
    calls: list[int] = []

    @logix.capability(idempotent=True)
    def charge(order_id: int, amount: float) -> dict[str, int]:
        calls.append(order_id)
        return {"ok": 1}

    logix.run({"call": "charge", "with": {"order_id": 1, "amount": 5.0}})
    logix.run({"call": "charge", "with": {"order_id": 2, "amount": 5.0}})
    assert len(calls) == 2


def test_non_idempotent_capability_calls_always(logix):
    calls: list[int] = []

    @logix.capability
    def charge(order_id: int, amount: float) -> dict[str, int]:
        calls.append(order_id)
        return {"ok": 1}

    logix.run({"call": "charge", "with": {"order_id": 1, "amount": 5.0}})
    logix.run({"call": "charge", "with": {"order_id": 1, "amount": 5.0}})
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Snapshot-hash mismatch
# ---------------------------------------------------------------------------


def test_registry_change_between_verify_and_execute_rejected(logix):
    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    report = logix.verify({"call": "add", "with": {"a": 1, "b": 2}})
    assert report.ok

    # Mutate the registry.
    logix.capability.unregister("add")

    result = logix.execute(report.verified_plan)
    assert not result.ok
    assert result.errors[0].code == "POLICY_REJECTED"
    assert "registry changed" in result.errors[0].message


# ---------------------------------------------------------------------------
# Audit hook
# ---------------------------------------------------------------------------


def test_audit_hook_fires_on_success(logix):
    events: list[tuple] = []

    class H:
        def on_step(self, e):
            events.append(("step", e["capability"], e["status"]))

        def on_result(self, e):
            events.append(("result", e["ok"]))

    logix.audit(H())

    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    logix.run({"call": "add", "with": {"a": 1, "b": 2}})
    assert ("step", "add", "ok") in events
    assert ("result", True) in events


def test_audit_hook_fires_on_failure(logix):
    events: list[tuple] = []

    class H:
        def on_step(self, e):
            events.append(("step", e["status"]))

        def on_result(self, e):
            events.append(("result", e["ok"]))

    logix.audit(H())

    @logix.capability
    def fail(x: int) -> int:
        raise ValueError("boom")

    logix.run({"call": "fail", "with": {"x": 1}})
    assert ("step", "failed") in events
    assert ("result", False) in events


def test_audit_hook_exception_does_not_break_execution(logix):
    class BadHook:
        def on_step(self, e):
            raise RuntimeError("auditor down")

        def on_result(self, e):
            raise RuntimeError("auditor down")

    logix.audit(BadHook())

    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    result = logix.run({"call": "add", "with": {"a": 1, "b": 2}})
    assert result.ok  # broken auditor must not block legitimate actions


# ---------------------------------------------------------------------------
# Trace population
# ---------------------------------------------------------------------------


def test_trace_populated_on_success(logix):
    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    result = logix.run({"call": "add", "with": {"a": 1, "b": 2}})
    assert result.trace is not None
    assert len(result.trace.steps) == 1
    assert result.trace.steps[0].capability == "add"
    assert result.trace.steps[0].status == "ok"


def test_trace_populated_on_failure(logix):
    @logix.capability
    def fail(x: int) -> int:
        raise ValueError("boom")

    result = logix.run({"call": "fail", "with": {"x": 1}})
    assert result.trace is not None
    assert result.trace.steps[0].status == "failed"
    assert result.trace.steps[0].error_code == "HANDLER_FAILED"


# ---------------------------------------------------------------------------
# The trust-boundary posture: direct invocation bypasses everything
# ---------------------------------------------------------------------------


def test_direct_handler_call_bypasses_pipeline(logix):
    # Logix is a boundary; it does not wrap the function. Direct calls
    # receive no validation — that is the documented design.
    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b  # type: ignore[operator]

    result = add("1", "2")  # type: ignore[arg-type]
    assert result == "12"  # ordinary Python string concat
