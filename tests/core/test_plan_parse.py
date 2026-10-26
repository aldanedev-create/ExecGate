"""
Plan parsing.

``parse_plan`` returns a ``CanonicalPlan`` on success or ``list[Error]``
on failure. It enforces structure only — capability resolution and
argument validation are the verifier's job.
"""

from __future__ import annotations

from logiq.errors import Error
from logiq.plans import (
    CanonicalPlan,
    PlanLimits,
    parse_plan,
)


def _errors(result) -> list[Error]:
    assert isinstance(result, list)
    assert all(isinstance(e, Error) for e in result)
    return result


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------


def test_single_call():
    result = parse_plan({"call": "add", "with": {"a": 1, "b": 2}})
    assert isinstance(result, CanonicalPlan)
    assert result.single_call is True
    assert result.version == "1"
    assert len(result.steps) == 1
    assert result.steps[0].id == ""  # single-call has no step id
    assert result.steps[0].capability == "add"
    assert dict(result.steps[0].arguments) == {"a": 1, "b": 2}


def test_multi_step():
    plan = {
        "version": "1",
        "steps": [
            {"id": "a", "call": "x", "with": {}},
            {"id": "b", "call": "y", "with": {"x": 1}},
        ],
    }
    result = parse_plan(plan)
    assert isinstance(result, CanonicalPlan)
    assert result.single_call is False
    assert len(result.steps) == 2
    assert result.steps[0].id == "a"


def test_multi_step_with_ref():
    plan = {
        "version": "1",
        "steps": [
            {"id": "a", "call": "x", "with": {}},
            {"id": "b", "call": "y", "with": {"r": {"$ref": "a.id"}}},
        ],
    }
    result = parse_plan(plan)
    assert isinstance(result, CanonicalPlan)
    assert len(result.steps) == 2


def test_json_string_input():
    result = parse_plan('{"call": "add", "with": {"a": 1}}')
    assert isinstance(result, CanonicalPlan)


# ---------------------------------------------------------------------------
# Structural errors
# ---------------------------------------------------------------------------


def test_missing_call_and_steps():
    errors = _errors(parse_plan({}))
    assert any("either 'call' or 'steps'" in e.message for e in errors)


def test_both_call_and_steps():
    errors = _errors(
        parse_plan(
            {
                "call": "x",
                "with": {},
                "steps": [{"id": "s", "call": "y", "with": {}}],
            }
        )
    )
    assert any("both" in e.message for e in errors)


def test_unknown_top_level_field():
    errors = _errors(parse_plan({"call": "x", "with": {}, "evil": True}))
    assert any("unknown top-level" in e.message for e in errors)


def test_unknown_step_field():
    plan = {
        "version": "1",
        "steps": [{"id": "s", "call": "x", "with": {}, "evil": 1}],
    }
    errors = _errors(parse_plan(plan))
    assert any("unknown step fields" in e.message for e in errors)


def test_duplicate_step_id():
    plan = {
        "version": "1",
        "steps": [
            {"id": "s", "call": "x", "with": {}},
            {"id": "s", "call": "y", "with": {}},
        ],
    }
    errors = _errors(parse_plan(plan))
    assert any("duplicate step id" in e.message for e in errors)


def test_non_string_call():
    errors = _errors(parse_plan({"call": 42, "with": {}}))
    assert any("non-empty string" in e.message for e in errors)


def test_non_list_steps():
    errors = _errors(parse_plan({"version": "1", "steps": "not-a-list"}))
    assert any("must be a list" in e.message for e in errors)


def test_step_missing_id():
    plan = {"version": "1", "steps": [{"call": "x", "with": {}}]}
    errors = _errors(parse_plan(plan))
    assert any("'id'" in e.message for e in errors)


def test_step_missing_call():
    plan = {"version": "1", "steps": [{"id": "s", "with": {}}]}
    errors = _errors(parse_plan(plan))
    assert any("'call'" in e.message for e in errors)


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------


def test_unsupported_version_rejected():
    plan = {"version": "999", "steps": []}
    errors = _errors(parse_plan(plan))
    assert any("unsupported plan version" in e.message for e in errors)


# ---------------------------------------------------------------------------
# Forward references
# ---------------------------------------------------------------------------


def test_forward_ref_rejected():
    plan = {
        "version": "1",
        "steps": [
            {"id": "a", "call": "x", "with": {"r": {"$ref": "b.id"}}},
            {"id": "b", "call": "y", "with": {}},
        ],
    }
    errors = _errors(parse_plan(plan))
    assert any("non-earlier" in e.message for e in errors)


def test_self_ref_rejected():
    plan = {
        "version": "1",
        "steps": [{"id": "a", "call": "x", "with": {"r": {"$ref": "a.id"}}}],
    }
    errors = _errors(parse_plan(plan))
    assert any("non-earlier" in e.message for e in errors)


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


def test_max_steps_exceeded():
    plan = {
        "version": "1",
        "steps": [{"id": f"s{i}", "call": "x", "with": {}} for i in range(100)],
    }
    errors = _errors(parse_plan(plan, limits=PlanLimits(max_steps=5)))
    assert any("max_steps" in e.message for e in errors)


def test_max_bytes_exceeded():
    plan = {"call": "x", "with": {"data": "a" * 10_000}}
    errors = _errors(parse_plan(plan, limits=PlanLimits(max_bytes=1000)))
    assert any("max_bytes" in e.message for e in errors)


def test_max_depth_exceeded():
    nested = 1
    for _ in range(20):
        nested = {"n": nested}
    plan = {"call": "x", "with": nested}
    errors = _errors(parse_plan(plan, limits=PlanLimits(max_depth=5)))
    assert any("max_depth" in e.message for e in errors)
