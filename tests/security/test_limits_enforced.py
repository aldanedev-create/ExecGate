"""
Resource limits are enforced before any handler runs.

``plans.parse`` enforces ``max_bytes``, ``max_steps``, ``max_depth``.
When exceeded, the plan is rejected and no handler is invoked. The
``max_invocations`` limit is available on ``PlanLimits`` but not yet
wired into the executor — this test documents the current state.
"""

from __future__ import annotations

import pytest

from execgate import Logix
from execgate.plans import DEFAULT_LIMITS, PlanLimits

# ---------------------------------------------------------------------------
# max_bytes
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_max_bytes_enforced(logix):
    invoked = []

    @logix.capability
    def op(x: int) -> int:
        invoked.append(x)
        return x

    logix.limits(max_bytes=200)
    big_payload = {"data": "a" * 5000}
    result = logix.run({"call": "op", "with": {"x": 1}, **big_payload})
    assert not result.ok
    assert invoked == []
    # Unknown top-level field OR max_bytes — either way no invocation.
    assert result.errors[0].code == "INVALID_PLAN"


@pytest.mark.security
def test_max_bytes_via_parse_directly():
    from execgate.plans import parse_plan

    plan = {"call": "x", "with": {"data": "a" * 5000}}
    result = parse_plan(plan, limits=PlanLimits(max_bytes=100))
    assert isinstance(result, list)
    assert any("max_bytes" in e.message for e in result)


# ---------------------------------------------------------------------------
# max_steps
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_max_steps_enforced(logix):
    invoked = []

    @logix.capability
    def op(x: int) -> int:
        invoked.append(x)
        return x

    logix.limits(max_steps=2)

    result = logix.run(
        {
            "version": "1",
            "steps": [{"id": f"s{i}", "call": "op", "with": {"x": i}} for i in range(5)],
        }
    )
    assert not result.ok
    assert result.errors[0].code == "INVALID_PLAN"
    assert any("max_steps" in e.message for e in result.errors)
    assert invoked == []


@pytest.mark.security
def test_max_steps_boundary_accepted(logix):
    @logix.capability
    def op(x: int) -> int:
        return x

    logix.limits(max_steps=2)
    # Exactly at limit — should succeed.
    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "a", "call": "op", "with": {"x": 1}},
                {"id": "b", "call": "op", "with": {"x": 2}},
            ],
        }
    )
    assert result.ok


# ---------------------------------------------------------------------------
# max_depth
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_max_depth_enforced(logix):
    invoked = []

    @logix.capability
    def op(x: int) -> int:
        invoked.append(x)
        return x

    logix.limits(max_depth=3)

    nested: object = "leaf"
    for _ in range(20):
        nested = {"n": nested}

    result = logix.run({"call": "op", "with": {"x": 1, "data": nested}})
    assert not result.ok
    assert result.errors[0].code == "INVALID_PLAN"
    assert any("max_depth" in e.message for e in result.errors)
    assert invoked == []


# ---------------------------------------------------------------------------
# Engine defaults
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_engine_uses_documented_defaults():
    logix = Logix()
    assert logix._limits.max_bytes == DEFAULT_LIMITS.max_bytes
    assert logix._limits.max_steps == DEFAULT_LIMITS.max_steps
    assert logix._limits.max_depth == DEFAULT_LIMITS.max_depth


@pytest.mark.security
def test_engine_limits_override_is_isolated():
    a = Logix()
    b = Logix()
    a.limits(max_steps=1)

    assert a._limits.max_steps == 1
    assert b._limits.max_steps == DEFAULT_LIMITS.max_steps


# ---------------------------------------------------------------------------
# max_invocations — documented gap
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_max_invocations_field_exists():
    """The field is present for forward compatibility. It is NOT enforced
    by the executor in 0.1.0 — enforcement tests should be added when it
    is wired in."""
    assert DEFAULT_LIMITS.max_invocations == 64
    assert hasattr(PlanLimits(), "max_invocations")


# ---------------------------------------------------------------------------
# Ordering guarantee: limits fire at parse, before any handler
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_limits_fire_before_verification_and_execution(logix):
    """A limit violation is caught at parse, before the verifier or any
    handler runs. No handler can be invoked for an over-limit plan."""
    invoked = []

    @logix.capability
    def op(x: int) -> int:
        invoked.append(x)
        return x

    logix.limits(max_steps=1)

    # Two steps exceeds the limit; both are valid capabilities, but
    # parse_plan rejects before either can be dispatched.
    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "a", "call": "op", "with": {"x": 1}},
                {"id": "b", "call": "op", "with": {"x": 2}},
            ],
        }
    )
    assert not result.ok
    assert invoked == []
