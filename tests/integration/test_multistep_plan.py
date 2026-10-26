"""
Multi-step plans, end to end.

Covers: dependency ordering, ``$ref`` resolution, partial failure, and
the distinction between "rejected at parse/verify" (no handlers ran) and
"failed mid-execution" (earlier steps produced side effects).

The refund workflow is the canonical example: a read step (``get_order``)
feeds a write step (``issue_refund``) whose arguments are ``$ref``-bound
to the read's validated output.
"""

from __future__ import annotations

from logiq import Deny

# ---------------------------------------------------------------------------
# Happy path: linear chain
# ---------------------------------------------------------------------------


def test_linear_chain_succeeds(logix):
    # Native types are strict (no int -> float widening, bool is not int),
    # so the chained values are all ints and the declared types agree.
    @logix.capability
    def get_order(order_id: int) -> dict[str, int]:
        return {"id": order_id, "total": 50}

    @logix.capability
    def issue_refund(order_id: int, amount: int) -> dict[str, int]:
        return {"refunded": 1, "order_id": order_id}

    result = logix.run(
        {
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
    )

    assert result.ok, result.errors
    # Result.value is a dict of step outputs.
    assert result.value["o"] == {"id": 502, "total": 50}
    assert result.value["r"] == {"refunded": 1, "order_id": 502}


def test_step_execution_order_follows_dependencies(logix):
    """Steps run in dependency order, not declaration order if they
    disagree — though the parser rejects forward refs, so declaration
    order and dependency order always agree for parseable plans."""
    log: list[str] = []

    @logix.capability
    def a() -> int:
        log.append("a")
        return 1

    @logix.capability
    def b(x: int) -> int:
        log.append("b")
        return x + 1

    @logix.capability
    def c(x: int) -> int:
        log.append("c")
        return x * 2

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "s1", "call": "a", "with": {}},
                {"id": "s2", "call": "b", "with": {"x": {"$ref": "s1"}}},
                {"id": "s3", "call": "c", "with": {"x": {"$ref": "s2"}}},
            ],
        }
    )
    assert result.ok
    assert log == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Diamond dependencies
# ---------------------------------------------------------------------------


def test_diamond_dependencies(logix):
    log: list[str] = []

    @logix.capability
    def root() -> int:
        log.append("root")
        return 10

    @logix.capability
    def left(x: int) -> int:
        log.append("left")
        return x + 1

    @logix.capability
    def right(x: int) -> int:
        log.append("right")
        return x + 2

    @logix.capability
    def join(left_val: int, r: int) -> int:
        log.append("join")
        return left_val + r

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "root", "call": "root", "with": {}},
                {"id": "left", "call": "left", "with": {"x": {"$ref": "root"}}},
                {"id": "right", "call": "right", "with": {"x": {"$ref": "root"}}},
                {
                    "id": "join",
                    "call": "join",
                    "with": {"left_val": {"$ref": "left"}, "r": {"$ref": "right"}},
                },
            ],
        }
    )

    assert result.ok
    # Root must be first, join last, left/right in between (order between
    # them preserved by declaration order).
    assert log[0] == "root"
    assert log[-1] == "join"
    assert set(log) == {"root", "left", "right", "join"}


# ---------------------------------------------------------------------------
# Reference type checking
# ---------------------------------------------------------------------------


def test_ref_int_to_float_rejected(logix):
    """The verifier rejects ``int`` → ``float`` because ADR-0003 forbids
    implicit widening. The client must declare the field as ``float`` and
    supply a float, or use a step that returns ``float``."""

    @logix.capability
    def get_order(order_id: int) -> dict[str, int]:
        return {"id": order_id, "total": 50}

    @logix.capability
    def refund(amount: float) -> dict[str, int]:
        return {"ok": 1}

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "o", "call": "get_order", "with": {"order_id": 1}},
                {"id": "r", "call": "refund", "with": {"amount": {"$ref": "o.total"}}},
            ],
        }
    )
    assert not result.ok
    assert result.errors[0].code == "INVALID_REFERENCE"


def test_ref_missing_path_rejected(logix):
    @logix.capability
    def get_order(order_id: int) -> dict[str, int]:
        return {"id": order_id}

    @logix.capability
    def refund(amount: int) -> dict[str, int]:
        return {"ok": 1}

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "o", "call": "get_order", "with": {"order_id": 1}},
                {"id": "r", "call": "refund", "with": {"amount": {"$ref": "o.missing"}}},
            ],
        }
    )
    assert not result.ok
    assert result.errors[0].code == "INVALID_REFERENCE"


# ---------------------------------------------------------------------------
# Partial failure
# ---------------------------------------------------------------------------


def test_partial_failure_stops_subsequent_steps(logix):
    log: list[str] = []

    @logix.capability
    def step_a() -> int:
        log.append("a")
        return 1

    @logix.capability
    def step_b(x: int) -> int:
        log.append("b")
        raise ValueError("boom")

    @logix.capability
    def step_c(x: int) -> int:
        log.append("c")
        return 3

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "a", "call": "step_a", "with": {}},
                {"id": "b", "call": "step_b", "with": {"x": {"$ref": "a"}}},
                {"id": "c", "call": "step_c", "with": {"x": {"$ref": "b"}}},
            ],
        }
    )

    assert not result.ok
    assert result.errors[0].code == "HANDLER_FAILED"
    # Steps a and b attempted; c never ran.
    assert log == ["a", "b"]


def test_partial_failure_reports_which_steps_ran(logix):
    @logix.capability
    def ok_step() -> int:
        return 1

    @logix.capability
    def fail_step(x: int) -> int:
        raise ValueError("boom")

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "ok", "call": "ok_step", "with": {}},
                {"id": "fail", "call": "fail_step", "with": {"x": {"$ref": "ok"}}},
            ],
        }
    )

    assert not result.ok
    assert result.trace is not None
    # Trace records both attempted steps.
    statuses = {s.step_id: s.status for s in result.trace.steps}
    assert statuses["ok"] == "ok"
    assert statuses["fail"] == "failed"


def test_pre_execution_failure_produces_no_side_effects(logix):
    """A verify-time failure happens before any handler runs — the plan
    never reaches the executor."""
    invoked: list[str] = []

    @logix.capability
    def step_a() -> int:
        invoked.append("a")
        return 1

    @logix.capability
    def step_b(x: int) -> int:
        invoked.append("b")
        return 2

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "a", "call": "step_a", "with": {}},
                # Unknown capability: rejected at verify.
                {"id": "b", "call": "no_such_cap", "with": {}},
            ],
        }
    )
    assert not result.ok
    assert result.errors[0].code == "UNKNOWN_CAPABILITY"
    assert invoked == []


# ---------------------------------------------------------------------------
# Invariants in multi-step plans
# ---------------------------------------------------------------------------


def test_invariant_fires_per_step(logix):
    """Each step's invariant runs before that step's handler."""
    invoked: list[str] = []

    @logix.capability
    def safe(x: int) -> int:
        invoked.append("safe")
        return x

    @logix.capability
    def dangerous(x: int) -> int:
        invoked.append("dangerous")
        return x

    logix.authorize(dangerous, check=lambda args, ctx: Deny("BLOCKED", "no"))

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "s1", "call": "safe", "with": {"x": 1}},
                {"id": "s2", "call": "dangerous", "with": {"x": {"$ref": "s1"}}},
            ],
        }
    )

    assert not result.ok
    assert result.errors[0].code == "POLICY_REJECTED"
    # safe ran (invariant passed for it); dangerous did NOT run.
    assert invoked == ["safe"]


# ---------------------------------------------------------------------------
# Multi-step vs single-call result shape
# ---------------------------------------------------------------------------


def test_multistep_result_is_dict_not_value(logix):
    @logix.capability
    def only() -> int:
        return 42

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "s", "call": "only", "with": {}},
            ],
        }
    )
    # Even a single-step multi-step plan returns a dict, not the raw value.
    # (Its shape comes from the plan form, not the step count.)
    assert result.ok
    assert isinstance(result.value, dict)
    assert result.value == {"s": 42}
