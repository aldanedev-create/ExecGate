"""
Dependency ordering and cycle detection.

``parse_plan`` rejects forward references (a step can only reference
*earlier* steps), so cycles cannot occur through normal parsing.
``_dependency_order`` still detects cycles defensively; tests here
exercise both the parse-level guard and the direct cycle check.
"""

from __future__ import annotations

from logix.plans import parse_plan
from logix.plans.parse import CanonicalPlan, CanonicalStep
from logix.verifier import _dependency_order


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

def test_single_call_order():
    plan = parse_plan({"call": "x", "with": {}})
    assert isinstance(plan, CanonicalPlan)
    order, errors = _dependency_order(plan)
    assert errors == []
    assert order == ["__single__"]


def test_linear_chain():
    plan = parse_plan({
        "version": "1",
        "steps": [
            {"id": "a", "call": "x", "with": {}},
            {"id": "b", "call": "y", "with": {"r": {"$ref": "a"}}},
        ],
    })
    assert isinstance(plan, CanonicalPlan)
    order, errors = _dependency_order(plan)
    assert errors == []
    assert order == ["a", "b"]


def test_independent_steps_preserve_declared_order():
    plan = parse_plan({
        "version": "1",
        "steps": [
            {"id": "a", "call": "x", "with": {}},
            {"id": "b", "call": "y", "with": {}},
        ],
    })
    assert isinstance(plan, CanonicalPlan)
    order, errors = _dependency_order(plan)
    assert errors == []
    assert order == ["a", "b"]


def test_diamond():
    plan = parse_plan({
        "version": "1",
        "steps": [
            {"id": "root", "call": "x", "with": {}},
            {"id": "left", "call": "y", "with": {"r": {"$ref": "root"}}},
            {"id": "right", "call": "z", "with": {"r": {"$ref": "root"}}},
            {"id": "join", "call": "w", "with": {
                "l": {"$ref": "left"}, "r": {"$ref": "right"},
            }},
        ],
    })
    assert isinstance(plan, CanonicalPlan)
    order, errors = _dependency_order(plan)
    assert errors == []
    assert order[0] == "root"
    assert order[-1] == "join"
    # left/right order not fixed beyond "after root, before join".


# ---------------------------------------------------------------------------
# Cycle detection (direct — cannot occur via parse)
# ---------------------------------------------------------------------------

def test_cycle_detected():
    a = CanonicalStep(id="a", capability="x", arguments={"r": {"$ref": "b"}})
    b = CanonicalStep(id="b", capability="y", arguments={"r": {"$ref": "a"}})
    plan = CanonicalPlan(version="1", steps=(a, b), single_call=False)

    order, errors = _dependency_order(plan)
    assert order == []
    assert len(errors) == 1
    assert errors[0].code == "DEPENDENCY_CYCLE"


def test_self_cycle_detected():
    a = CanonicalStep(id="a", capability="x", arguments={"r": {"$ref": "a"}})
    plan = CanonicalPlan(version="1", steps=(a,), single_call=False)

    order, errors = _dependency_order(plan)
    assert order == []
    assert len(errors) == 1
    assert errors[0].code == "DEPENDENCY_CYCLE"


# ---------------------------------------------------------------------------
# Parse-level guard (the actual contract: no forward refs -> no cycles)
# ---------------------------------------------------------------------------

def test_forward_ref_prevented_at_parse():
    """Cycles cannot reach the verifier through the parser's forward-ref
    rejection. This is the load-bearing guarantee."""
    result = parse_plan({
        "version": "1",
        "steps": [
            {"id": "a", "call": "x", "with": {"r": {"$ref": "b"}}},
            {"id": "b", "call": "y", "with": {"r": {"$ref": "a"}}},
        ],
    })
    assert isinstance(result, list), "cyclic plan must be rejected at parse"