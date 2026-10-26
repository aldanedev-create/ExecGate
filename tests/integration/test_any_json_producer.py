"""
Any JSON producer drives the same pipeline.

The core promise: **works with any AI that emits JSON**. A hand-written
dict, a JSON string, a neutral adapter's output, and a provider adapter's
output all flow through ``logix.run()`` — and receive *identical*
guarantees:

- Unknown capabilities rejected with ``UNKNOWN_CAPABILITY``
- Invalid arguments rejected with ``SCHEMA_VALIDATION_FAILED``
- Policy violations rejected with ``POLICY_REJECTED``
- Handlers invoked exactly when they should be, and never when they should not

The pipeline does not know or care where the plan came from. That is what
makes the boundary *structural* rather than *conditional on the caller*.
"""

from __future__ import annotations

import json

import pytest

from logiq import Deny, Logix

# ---------------------------------------------------------------------------
# Optional dependency: logiq_ai
# ---------------------------------------------------------------------------

try:
    from logiq_ai.neutral import NeutralJSONAdapter
    from logiq_ai.providers.openai import OpenAIAdapter

    HAS_LOGIX_AI = True
except ImportError:
    HAS_LOGIX_AI = False

requires_logix_ai = pytest.mark.skipif(
    not HAS_LOGIX_AI,
    reason="logiq_ai not installed",
)


# ---------------------------------------------------------------------------
# Helper: a fixed plan and engine
# ---------------------------------------------------------------------------


def _engine() -> Logix:
    """A fresh engine with a single ``add`` capability."""
    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    return logix


# ---------------------------------------------------------------------------
# Every producer produces the same *plan*; every plan gets the same result
# ---------------------------------------------------------------------------


def _valid_plans() -> dict[str, object]:
    """Four ways to construct the same logical plan: {"call": "add", "with": {"a": 3, "b": 4}}"""
    canonical = {"call": "add", "with": {"a": 3, "b": 4}}

    plans: dict[str, object] = {
        # 1. Hand-written dict — no AI involved at all.
        "hand_dict": canonical,
        # 2. JSON string — as a user would type or a script would emit.
        "json_string": json.dumps(canonical),
    }

    if HAS_LOGIX_AI:
        # 3. Neutral adapter output — the "any JSON" path.
        plans["neutral"] = NeutralJSONAdapter().parse_proposal(
            {"call": "add", "with": {"a": 3, "b": 4}}
        )
        # 4. OpenAI adapter output — the "one specific provider" path.
        plans["openai"] = OpenAIAdapter().parse_proposal(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "add",
                                        "arguments": '{"a": 3, "b": 4}',
                                    }
                                },
                            ]
                        }
                    }
                ],
            }
        )

    return plans


@pytest.mark.parametrize("producer_name", list(_valid_plans().keys()))
def test_every_producer_yields_same_plan(producer_name):
    plan = _valid_plans()[producer_name]
    from logiq.plans import CanonicalPlan, parse_plan

    parsed = parse_plan(plan)
    assert isinstance(parsed, CanonicalPlan)
    assert parsed.steps[0].capability == "add"
    assert dict(parsed.steps[0].arguments) == {"a": 3, "b": 4}


@pytest.mark.parametrize("producer_name", list(_valid_plans().keys()))
def test_every_producer_yields_same_result(producer_name):
    logix = _engine()
    result = logix.run(_valid_plans()[producer_name])
    assert result.ok, result.errors
    assert result.value == 7


# ---------------------------------------------------------------------------
# A hand-written dict is an untrusted plan, exactly like an AI proposal
# ---------------------------------------------------------------------------


def test_handwritten_dict_rejected_on_unknown_capability():
    invoked: list[int] = []

    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        invoked.append(1)
        return a + b

    result = logix.run({"call": "does_not_exist", "with": {}})
    assert not result.ok
    assert result.errors[0].code == "UNKNOWN_CAPABILITY"
    assert invoked == []


def test_handwritten_dict_rejected_on_schema_violation():
    invoked: list[int] = []

    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        invoked.append(1)
        return a + b

    result = logix.run({"call": "add", "with": {"a": "not-an-int", "b": 2}})
    assert not result.ok
    assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"
    assert invoked == []


def test_handwritten_dict_rejected_by_invariant():
    invoked: list[int] = []

    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        invoked.append(1)
        return a + b

    logix.authorize(add, check=lambda args, ctx: Deny("BLOCKED", "no"))

    result = logix.run({"call": "add", "with": {"a": 1, "b": 2}})
    assert not result.ok
    assert result.errors[0].code == "POLICY_REJECTED"
    assert invoked == []


# ---------------------------------------------------------------------------
# The boundary doesn't know or care about the source
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("producer_name", list(_valid_plans().keys()))
def test_schema_violation_rejected_identically(producer_name):
    """Same policy, same schema — every producer receives the same
    rejection code and never invokes a handler."""
    invoked: list[int] = []

    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        invoked.append(1)
        return a + b

    # Build a producer's output, then corrupt the argument to violate schema.
    bad_plans: dict[str, object] = {
        "hand_dict": {"call": "add", "with": {"a": "wrong", "b": 2}},
        "json_string": '{"call": "add", "with": {"a": "wrong", "b": 2}}',
    }
    if HAS_LOGIX_AI:
        bad_plans["neutral"] = NeutralJSONAdapter().parse_proposal(
            {"call": "add", "with": {"a": "wrong", "b": 2}}
        )
        bad_plans["openai"] = OpenAIAdapter().parse_proposal(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "add",
                                        "arguments": '{"a": "wrong", "b": 2}',
                                    }
                                },
                            ]
                        }
                    }
                ],
            }
        )

    result = logix.run(bad_plans[producer_name])
    assert not result.ok
    assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"
    assert invoked == []


# ---------------------------------------------------------------------------
# The smuggle-verified test: no producer can inject "verified": true
# ---------------------------------------------------------------------------


def test_handwritten_dict_smuggling_verified_rejected():
    logix = _engine()
    result = logix.run(
        {
            "call": "add",
            "with": {"a": 1, "b": 2},
            "verified": True,  # attempted bypass
        }
    )
    assert not result.ok
    assert result.errors[0].code == "INVALID_PLAN"


@requires_logix_ai
def test_neutral_adapter_smuggling_verified_rejected():
    """Even if a hypothetical buggy adapter let "verified": true through,
    plans.parse rejects it before the verifier."""
    logix = _engine()
    smuggled = {
        "call": "add",
        "with": {"a": 1, "b": 2},
        "verified": True,
    }
    # Bypass the adapter and call logix.run directly with the smuggled
    # proposal — proving the parser is the boundary, not the adapter.
    result = logix.run(smuggled)
    assert not result.ok
    assert result.errors[0].code == "INVALID_PLAN"


# ---------------------------------------------------------------------------
# Equivalence across producers, including on failures
# ---------------------------------------------------------------------------


def test_all_producers_produce_identical_error_codes_on_failure():
    """A plan is a plan is a plan. The same semantic plan produces the same
    error code regardless of which JSON producer emitted it."""
    invoked: list[int] = []

    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        invoked.append(1)
        return a + b

    logix.authorize(add, check=lambda args, ctx: Deny("BLOCKED", "no"))

    codes: dict[str, str] = {}
    producers: dict[str, object] = {
        "hand_dict": {"call": "add", "with": {"a": 1, "b": 2}},
        "json_string": '{"call": "add", "with": {"a": 1, "b": 2}}',
    }
    if HAS_LOGIX_AI:
        producers["neutral"] = NeutralJSONAdapter().parse_proposal(
            {"call": "add", "with": {"a": 1, "b": 2}}
        )
        producers["openai"] = OpenAIAdapter().parse_proposal(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {"function": {"name": "add", "arguments": '{"a": 1, "b": 2}'}},
                            ]
                        }
                    }
                ],
            }
        )

    for name, plan in producers.items():
        result = logix.run(plan)
        assert not result.ok
        codes[name] = result.errors[0].code

    # Every producer received the same error code.
    assert set(codes.values()) == {"POLICY_REJECTED"}
    # Handler never invoked for any of them.
    assert invoked == []


# ---------------------------------------------------------------------------
# Multi-step via hand-written plan
# ---------------------------------------------------------------------------


def test_handwritten_multistep_plan_works_end_to_end():
    """No AI, no adapter, no provider SDK — just two dicts. Full pipeline."""
    logix = Logix()
    invoked: list[str] = []

    @logix.capability
    def a(x: int) -> int:
        invoked.append("a")
        return x + 1

    @logix.capability
    def b(x: int) -> int:
        invoked.append("b")
        return x * 2

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "one", "call": "a", "with": {"x": 5}},
                {"id": "two", "call": "b", "with": {"x": {"$ref": "one"}}},
            ],
        }
    )

    assert result.ok, result.errors
    assert invoked == ["a", "b"]
    assert result.value == {"one": 6, "two": 12}
