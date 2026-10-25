"""
Grounding policy: sensitive arguments must come from a ``$ref``.

``GroundingPolicy`` validates its own configuration at construction;
``check_grounding`` returns ``GROUNDING_REQUIRED`` for any sensitive
argument whose value is a bare literal. Runs during ``logix.verify()``,
before the verifier.
"""

from __future__ import annotations

import pytest

from logix import Logix
from logix.plans import CanonicalPlan, CanonicalStep
from logix.semantic import GroundingPolicy, check_grounding


def _plan(capability: str, args: dict) -> CanonicalPlan:
    return CanonicalPlan(
        version="1",
        steps=(CanonicalStep(id="", capability=capability, arguments=args),),
        single_call=True,
    )


# ---------------------------------------------------------------------------
# GroundingPolicy construction
# ---------------------------------------------------------------------------

def test_empty_policy_is_valid():
    policy = GroundingPolicy()
    assert policy.require_ref == frozenset()
    assert policy.literal_allowlist == frozenset()


def test_valid_paths_accepted():
    policy = GroundingPolicy(
        require_ref=frozenset({"refund.amount", "refund.line_items.0.amount"}),
        literal_allowlist=frozenset({"get_order.order_id"}),
    )
    assert "refund.amount" in policy.require_ref


def test_path_without_dot_rejected():
    with pytest.raises(ValueError, match="capability.argument"):
        GroundingPolicy(require_ref=frozenset({"justname"}))


def test_path_starting_with_dot_rejected():
    with pytest.raises(ValueError):
        GroundingPolicy(require_ref=frozenset({".bad"}))


def test_path_ending_with_dot_rejected():
    with pytest.raises(ValueError):
        GroundingPolicy(require_ref=frozenset({"bad."}))


# ---------------------------------------------------------------------------
# check_grounding — empty policy
# ---------------------------------------------------------------------------

def test_empty_policy_produces_no_errors():
    plan = _plan("refund", {"amount": 5.0})
    assert check_grounding(plan, GroundingPolicy()) == []


# ---------------------------------------------------------------------------
# check_grounding — literal rejected
# ---------------------------------------------------------------------------

def test_literal_value_rejected():
    plan = _plan("refund", {"amount": 5.0})
    policy = GroundingPolicy(require_ref=frozenset({"refund.amount"}))

    errors = check_grounding(plan, policy)
    assert len(errors) == 1
    assert errors[0].code == "GROUNDING_REQUIRED"
    assert errors[0].details["capability"] == "refund"
    assert errors[0].details["argument"] == "amount"


def test_non_sensitive_literal_allowed():
    plan = _plan("refund", {"order_id": 1, "amount": 5.0})
    policy = GroundingPolicy(require_ref=frozenset({"refund.amount"}))

    # order_id is not required to be a ref, amount is.
    errors = check_grounding(plan, policy)
    assert len(errors) == 1
    assert errors[0].details["argument"] == "amount"


# ---------------------------------------------------------------------------
# check_grounding — $ref accepted
# ---------------------------------------------------------------------------

def test_ref_value_accepted():
    plan = _plan("refund", {"amount": {"$ref": "order.total"}})
    policy = GroundingPolicy(require_ref=frozenset({"refund.amount"}))
    assert check_grounding(plan, policy) == []


# ---------------------------------------------------------------------------
# literal_allowlist
# ---------------------------------------------------------------------------

def test_allowlist_overrides_require_ref():
    plan = _plan("refund", {"amount": 5.0})
    policy = GroundingPolicy(
        require_ref=frozenset({"refund.amount"}),
        literal_allowlist=frozenset({"refund.amount"}),
    )
    assert check_grounding(plan, policy) == []


def test_allowlist_does_not_affect_other_paths():
    plan = _plan("refund", {"amount": 5.0, "note": "x"})
    policy = GroundingPolicy(
        require_ref=frozenset({"refund.amount", "refund.note"}),
        literal_allowlist=frozenset({"refund.note"}),
    )
    errors = check_grounding(plan, policy)
    assert len(errors) == 1
    assert errors[0].details["argument"] == "amount"


# ---------------------------------------------------------------------------
# Nested arguments
# ---------------------------------------------------------------------------

def test_nested_dict_path():
    plan = _plan("refund", {"line_items": {"first": 5.0}})
    policy = GroundingPolicy(require_ref=frozenset({"refund.line_items.first"}))
    errors = check_grounding(plan, policy)
    assert len(errors) == 1
    assert errors[0].details["argument"] == "line_items.first"


def test_list_index_path():
    plan = _plan("refund", {"line_items": [{"amount": 5.0}, {"amount": 6.0}]})
    policy = GroundingPolicy(require_ref=frozenset({
        "refund.line_items.0.amount",
        "refund.line_items.1.amount",
    }))
    errors = check_grounding(plan, policy)
    assert len(errors) == 2


# ---------------------------------------------------------------------------
# End-to-end via Logix
# ---------------------------------------------------------------------------

def test_verify_fails_for_ungrounded_literal(logix):
    @logix.capability
    def refund(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    logix.grounding(require_ref_for=["refund.amount"])

    report = logix.verify({
        "call": "refund",
        "with": {"order_id": 1, "amount": 5.0},
    })
    assert not report.ok
    assert report.errors[0].code == "GROUNDING_REQUIRED"


def test_verify_passes_when_amount_is_ref(logix):
    @logix.capability
    def get_order(order_id: int) -> dict[str, float]:
        return {"total": 50.0}

    @logix.capability
    def refund(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    logix.grounding(require_ref_for=["refund.amount"])

    report = logix.verify({
        "version": "1",
        "steps": [
            {"id": "o", "call": "get_order", "with": {"order_id": 1}},
            {"id": "r", "call": "refund",
             "with": {"order_id": 1, "amount": {"$ref": "o.total"}}},
        ],
    })
    assert report.ok


def test_run_fails_grounding_before_handler(logix):
    invoked = []

    @logix.capability
    def refund(order_id: int, amount: float) -> dict[str, int]:
        invoked.append(1)
        return {"ok": 1}

    logix.grounding(require_ref_for=["refund.amount"])

    result = logix.run({
        "call": "refund",
        "with": {"order_id": 1, "amount": 5.0},
    })
    assert not result.ok
    assert result.errors[0].code == "GROUNDING_REQUIRED"
    assert invoked == []