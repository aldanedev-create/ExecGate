"""
Reference cycles and forward references are rejected before any handler runs.

Two layers of defense:

1. ``plans.parse`` rejects forward references (a step can only ``$ref`` an
   *earlier* step). This makes cycles impossible to construct through
   normal parsing.
2. ``verifier._dependency_order`` detects cycles defensively, in case a
   ``CanonicalPlan`` is constructed directly with a cycle.

Both paths are tested. Neither invokes a handler.
"""

from __future__ import annotations

import pytest

from logix.plans.parse import CanonicalPlan, CanonicalStep
from logix.verifier import _dependency_order


@pytest.mark.security
def test_forward_ref_rejected_at_parse(logix):
    """A step cannot reference a later step. This is the primary defense
    against cycles."""
    invoked = []

    @logix.capability
    def cap(x: int) -> int:
        invoked.append(x)
        return x

    result = logix.run({
        "version": "1",
        "steps": [
            {"id": "a", "call": "cap", "with": {"x": 1}},
            {"id": "b", "call": "cap",
             "with": {"x": {"$ref": "c"}}},  # forward ref to c
            {"id": "c", "call": "cap", "with": {"x": 3}},
        ],
    })
    assert not result.ok
    # Forward ref caught at parse: INVALID_PLAN or INVALID_REFERENCE.
    assert result.errors[0].code in {"INVALID_PLAN", "INVALID_REFERENCE"}
    assert invoked == []


@pytest.mark.security
def test_self_ref_rejected(logix):
    invoked = []

    @logix.capability
    def cap(x: int) -> int:
        invoked.append(x)
        return x

    result = logix.run({
        "version": "1",
        "steps": [
            {"id": "a", "call": "cap", "with": {"x": {"$ref": "a"}}},
        ],
    })
    assert not result.ok
    assert invoked == []


@pytest.mark.security
def test_direct_cycle_detected_by_verifier():
    """Even if a CanonicalPlan is constructed with a cycle, the verifier
    detects it. This exercises the defensive path."""
    a = CanonicalStep(id="a", capability="x", arguments={"r": {"$ref": "b"}})
    b = CanonicalStep(id="b", capability="y", arguments={"r": {"$ref": "a"}})
    plan = CanonicalPlan(version="1", steps=(a, b), single_call=False)

    order, errors = _dependency_order(plan)
    assert order == []
    assert len(errors) == 1
    assert errors[0].code == "DEPENDENCY_CYCLE"


@pytest.mark.security
def test_cycle_handler_never_invoked(logix):
    """Full-stack check: a plan whose only possible interpretation is a
    cycle never runs a handler."""
    invoked = []

    @logix.capability
    def cap(x: int) -> int:
        invoked.append(x)
        return x

    # A valid plan is required to exercise the pipeline; if the cycle
    # smuggles through, we'd see invoked != []. Since the parser rejects
    # forward refs, this yields a parse error.
    logix.run({
        "version": "1",
        "steps": [
            {"id": "a", "call": "cap", "with": {"x": {"$ref": "b"}}},
            {"id": "b", "call": "cap", "with": {"x": {"$ref": "a"}}},
        ],
    })
    assert invoked == []


@pytest.mark.security
def test_dag_with_diamond_dependency_succeeds(logix):
    """Sanity: legitimate DAGs work. Cycles being rejected does not
    mean all dependency graphs are."""
    calls: list[str] = []

    @logix.capability
    def a() -> int:
        calls.append("a")
        return 1

    @logix.capability
    def b(x: int) -> int:
        calls.append("b")
        return x + 1

    @logix.capability
    def c(x: int) -> int:
        calls.append("c")
        return x * 2

    result = logix.run({
        "version": "1",
        "steps": [
            {"id": "root", "call": "a", "with": {}},
            {"id": "left", "call": "b", "with": {"x": {"$ref": "root"}}},
            {"id": "right", "call": "c", "with": {"x": {"$ref": "root"}}},
        ],
    })
    assert result.ok
    assert calls[0] == "a"
    assert set(calls) == {"a", "b", "c"}