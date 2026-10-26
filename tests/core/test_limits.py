"""
Resource limits.

``PlanLimits`` enforces caps on plan size, step count, and nesting depth
at parse time. The engine's ``limits()`` method overrides one or more
limits for subsequent verifications without resetting the others.
"""

from __future__ import annotations

import pytest

from logiq.plans import DEFAULT_LIMITS, PlanLimits, parse_plan


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_default_limits():
    assert DEFAULT_LIMITS.max_bytes == 64_000
    assert DEFAULT_LIMITS.max_steps == 32
    assert DEFAULT_LIMITS.max_depth == 8
    assert DEFAULT_LIMITS.max_invocations == 64


def test_limits_frozen():
    import dataclasses

    limits = PlanLimits()
    with pytest.raises(dataclasses.FrozenInstanceError):
        limits.max_steps = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def test_check_bytes_below_ok():
    PlanLimits(max_bytes=1000).check_bytes(500)


def test_check_bytes_above_raises():
    with pytest.raises(ValueError, match="max_bytes"):
        PlanLimits(max_bytes=100).check_bytes(101)


def test_check_bytes_at_boundary_ok():
    PlanLimits(max_bytes=100).check_bytes(100)


def test_check_steps_below_ok():
    PlanLimits(max_steps=5).check_steps(3)


def test_check_steps_above_raises():
    with pytest.raises(ValueError, match="max_steps"):
        PlanLimits(max_steps=2).check_steps(3)


def test_check_steps_at_boundary_ok():
    PlanLimits(max_steps=5).check_steps(5)


def test_check_depth_below_ok():
    PlanLimits(max_depth=5).check_depth(3)


def test_check_depth_above_raises():
    with pytest.raises(ValueError, match="max_depth"):
        PlanLimits(max_depth=3).check_depth(4)


# ---------------------------------------------------------------------------
# Enforcement via parse_plan
# ---------------------------------------------------------------------------

def test_max_steps_exceeded_at_parse():
    plan = {
        "version": "1",
        "steps": [{"id": f"s{i}", "call": "x", "with": {}} for i in range(10)],
    }
    result = parse_plan(plan, limits=PlanLimits(max_steps=5))
    assert isinstance(result, list)
    assert any("max_steps" in e.message for e in result)


def test_max_bytes_exceeded_at_parse():
    plan = {"call": "x", "with": {"data": "a" * 2000}}
    result = parse_plan(plan, limits=PlanLimits(max_bytes=100))
    assert isinstance(result, list)
    assert any("max_bytes" in e.message for e in result)


def test_max_depth_exceeded_at_parse():
    nested: object = 1
    for _ in range(20):
        nested = {"n": nested}
    plan = {"call": "x", "with": nested}
    result = parse_plan(plan, limits=PlanLimits(max_depth=5))
    assert isinstance(result, list)
    assert any("max_depth" in e.message for e in result)


def test_under_limits_succeeds():
    result = parse_plan(
        {"call": "x", "with": {"a": 1}},
        limits=PlanLimits(max_bytes=1000, max_steps=5, max_depth=5),
    )
    from logiq.plans import CanonicalPlan

    assert isinstance(result, CanonicalPlan)


# ---------------------------------------------------------------------------
# Engine override
# ---------------------------------------------------------------------------

def test_logix_limits_override(logix):
    original_bytes = logix._limits.max_bytes
    logix.limits(max_steps=5)
    assert logix._limits.max_steps == 5
    assert logix._limits.max_bytes == original_bytes  # unchanged


def test_logix_limits_override_enforced(logix):
    @logix.capability
    def f(x: int) -> int:
        return x

    logix.limits(max_steps=1)

    report = logix.verify({
        "version": "1",
        "steps": [
            {"id": "a", "call": "f", "with": {"x": 1}},
            {"id": "b", "call": "f", "with": {"x": 2}},
        ],
    })
    assert not report.ok
    assert any("max_steps" in e.message for e in report.errors)


def test_logix_limits_multiple_overrides(logix):
    logix.limits(max_steps=10, max_bytes=500, max_depth=6)
    assert logix._limits.max_steps == 10
    assert logix._limits.max_bytes == 500
    assert logix._limits.max_depth == 6
    # Untouched values keep their defaults.
    assert logix._limits.max_invocations == DEFAULT_LIMITS.max_invocations


def test_logix_limits_engine_isolation():
    """Two engines with different limits must not interfere."""
    from logiq import Logix

    a = Logix()
    b = Logix()
    a.limits(max_steps=2)

    assert a._limits.max_steps == 2
    assert b._limits.max_steps == DEFAULT_LIMITS.max_steps