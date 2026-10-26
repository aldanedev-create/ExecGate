"""
Property-based tests for ``plans.parse_plan``.

The parser is the first line of defense against untrusted input. Its
contract:

    parse_plan(x) -> CanonicalPlan | list[Error]

for any JSON-compatible ``x``. It must never:
- raise an uncaught exception,
- return a value that is neither of the two legal types,
- return an ``Error`` whose ``code`` is not in the stable taxonomy,
- allow a plain dict claiming ``{"verified": true}`` to succeed.

And for plans that parse successfully:
- Round-tripping through ``serialize`` → ``parse_plan`` produces an
  equivalent plan.
- Deterministic: same input → same output.
"""

from __future__ import annotations

import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from logiq.errors import ALL_CODES, Error
from logiq.plans import CanonicalPlan, parse_plan

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# JSON-compatible scalar. ``allow_nan=False`` keeps generated plans strictly
# JSON-representable — the real contract for an AI-generated plan.
_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**6), max_value=10**6),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=20),
)

_json_values = st.recursive(
    _json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=10), children, max_size=4),
    ),
    max_leaves=15,
)


@st.composite
def _valid_single_call_plan(draw):
    return {
        "call": draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "N", "Pc"),
                    max_codepoint=127,
                ),
                min_size=1,
                max_size=20,
            )
        ),
        "with": draw(
            st.dictionaries(
                st.text(min_size=1, max_size=15),
                _json_scalars,
                max_size=5,
            )
        ),
    }


@st.composite
def _valid_multistep_plan(draw):
    n = draw(st.integers(min_value=1, max_value=4))
    steps = []
    for i in range(n):
        step = {
            "id": f"s{i}",
            "call": f"cap{i}",
            "with": draw(
                st.dictionaries(
                    st.text(min_size=1, max_size=15),
                    _json_scalars,
                    max_size=3,
                )
            ),
        }
        steps.append(step)
    return {"version": "1", "steps": steps}


# ---------------------------------------------------------------------------
# The primary property: no crash, only the two legal return types
# ---------------------------------------------------------------------------


@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(value=_json_values)
def test_parse_never_crashes_and_returns_legal_type(value):
    """Any JSON-compatible value — dict, list, scalar — produces a
    ``CanonicalPlan`` or a ``list[Error]``. Never anything else."""
    result = parse_plan(value)

    if isinstance(result, CanonicalPlan):
        return  # legal success

    assert isinstance(result, list), (
        f"parse_plan returned {type(result).__name__}, expected CanonicalPlan or list[Error]"
    )
    assert len(result) >= 1, "failure must include at least one error"
    for error in result:
        assert isinstance(error, Error), f"non-Error in failure list: {type(error).__name__}"
        assert error.code in ALL_CODES, f"error code {error.code!r} not in the stable taxonomy"
        assert isinstance(error.message, str)
        assert error.message  # messages must be non-empty


@pytest.mark.parametrize(
    "input_value",
    [
        None,
        True,
        False,
        0,
        1,
        -1,
        0.0,
        1.5,
        "",
        "string",
        [],
        [1, 2],
        {},
    ],
)
def test_parse_handles_extreme_scalar_inputs(input_value):
    """A small set of extreme inputs parsed directly — no Hypothesis
    shrinking needed, failure reproduction is trivial."""
    result = parse_plan(input_value)
    if isinstance(result, CanonicalPlan):
        return
    assert isinstance(result, list)
    for error in result:
        assert error.code in ALL_CODES


# ---------------------------------------------------------------------------
# Valid plans always parse
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(plan=_valid_single_call_plan())
def test_valid_single_call_plans_parse(plan):
    result = parse_plan(plan)
    assert isinstance(result, CanonicalPlan), f"valid single-call plan failed: {result}"
    assert result.single_call is True
    assert len(result.steps) == 1
    assert result.steps[0].capability == plan["call"]
    assert dict(result.steps[0].arguments) == plan["with"]


@settings(max_examples=100, deadline=None)
@given(plan=_valid_multistep_plan())
def test_valid_multistep_plans_parse(plan):
    result = parse_plan(plan)
    assert isinstance(result, CanonicalPlan), (
        f"valid multi-step plan failed: "
        f"{[e.message for e in result] if isinstance(result, list) else '?'}"
    )
    assert result.single_call is False
    assert len(result.steps) == len(plan["steps"])
    assert [s.id for s in result.steps] == [s["id"] for s in plan["steps"]]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(plan=_valid_single_call_plan())
def test_parse_is_deterministic(plan):
    """Same input twice → same output."""
    r1 = parse_plan(plan)
    r2 = parse_plan(plan)
    if isinstance(r1, CanonicalPlan):
        assert isinstance(r2, CanonicalPlan)
        assert r1.version == r2.version
        assert [s.id for s in r1.steps] == [s.id for s in r2.steps]
        assert [s.capability for s in r1.steps] == [s.capability for s in r2.steps]
        assert [dict(s.arguments) for s in r1.steps] == [dict(s.arguments) for s in r2.steps]
    else:
        assert isinstance(r2, list)
        assert len(r1) == len(r2)
        assert [e.code for e in r1] == [e.code for e in r2]


# ---------------------------------------------------------------------------
# Round-trip through serialization
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(plan=_valid_single_call_plan())
def test_round_trip_through_serialization(plan):
    """parse → serialize to a fresh plan dict → parse → same shape."""
    first = parse_plan(plan)
    assert isinstance(first, CanonicalPlan)

    # Reconstruct a plan dict that should parse to the same structure.
    reconstructed = {
        "call": first.steps[0].capability,
        "with": dict(first.steps[0].arguments),
    }
    second = parse_plan(reconstructed)
    assert isinstance(second, CanonicalPlan)
    assert second.single_call is True
    assert second.steps[0].capability == first.steps[0].capability
    assert dict(second.steps[0].arguments) == dict(first.steps[0].arguments)


# ---------------------------------------------------------------------------
# Adversarial: smuggled "verified" flag cannot succeed
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(plan=_valid_single_call_plan())
def test_smuggled_verified_flag_always_rejected(plan):
    """Adding ``"verified": true`` to a valid plan must always fail at parse."""
    smuggled = dict(plan)
    smuggled["verified"] = True
    result = parse_plan(smuggled)
    assert isinstance(result, list), "smuggled 'verified' flag reached CanonicalPlan"
    assert any(e.code == "INVALID_PLAN" for e in result)


# ---------------------------------------------------------------------------
# Limits are respected as documented
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(plan=_valid_single_call_plan())
def test_oversized_plan_rejected(plan):
    """A plan larger than the byte limit is rejected before parsing
    succeeds."""
    from logiq.plans import PlanLimits

    # Serialize, then set a limit smaller than the resulting bytes.
    # Must match parse_plan's canonical (compact) serialization.
    size = len(json.dumps(plan, separators=(",", ":"), default=str).encode("utf-8"))
    tiny_limit = PlanLimits(max_bytes=max(1, size - 1))
    result = parse_plan(plan, limits=tiny_limit)
    assert isinstance(result, list)
    assert any("max_bytes" in e.message for e in result)


# ---------------------------------------------------------------------------
# Known limitation: parse_plan doesn't catch all exceptions during
# size calculation. Documented, not enforced — see file docstring.
# ---------------------------------------------------------------------------


def test_plan_with_unstringable_object_rejected():
    """A plan containing an object whose __str__ raises must produce
    INVALID_PLAN, not a crash. The parser catches serialization failures
    broadly."""

    class Bad:
        def __str__(self):
            raise RuntimeError("nope")

    result = parse_plan({"call": "x", "with": {"o": Bad()}})

    assert isinstance(result, list), (
        "parse_plan returned a CanonicalPlan for an unserializable plan"
    )
    assert len(result) >= 1
    assert result[0].code == "INVALID_PLAN"
    assert "serialized" in result[0].message
