"""
The verifier: ``verify_plan`` produces a ``VerifiedPlan`` or errors.

All static checks (capability resolution, schema validation, reference
type checking, dependency order) are exercised here. Dynamic checks
(invariants, approval, idempotency) live in the executor and are tested
elsewhere.
"""

from __future__ import annotations

import pytest

from logiq.capabilities import Registry, build_capability
from logiq.ir import VerifiedPlan
from logiq.plans import DEFAULT_LIMITS, parse_plan
from logiq.verifier import verify_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _registry() -> Registry:
    reg = Registry()

    def get_order(order_id: int) -> dict[str, int]:
        return {"id": order_id}

    def get_customer(customer_id: int) -> dict[str, int]:
        return {"id": customer_id}

    def issue_refund(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    def noret() -> None:
        return None

    def no_output(x: int):  # unannotated return -> no output schema
        return x

    reg.add(build_capability(get_order))
    reg.add(build_capability(get_customer))
    reg.add(build_capability(issue_refund))
    reg.add(build_capability(noret))
    reg.add(build_capability(no_output))
    return reg


def _verify(plan_dict, reg=None):
    reg = reg if reg is not None else _registry()
    parsed = parse_plan(plan_dict)
    assert not isinstance(parsed, list), f"unexpected parse errors: {parsed}"
    return verify_plan(parsed, registry=reg, limits=DEFAULT_LIMITS)


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------

def test_valid_single_call():
    verified, errors = _verify({"call": "get_order", "with": {"order_id": 1}})
    assert errors == []
    assert isinstance(verified, VerifiedPlan)
    assert verified.single_call is True
    assert verified.plan_version == "1"
    assert len(verified.steps) == 1
    assert verified.steps[0].capability == "get_order"
    assert verified.dependency_order == ("__single__",)


def test_valid_multi_step_with_ref():
    plan = {
        "version": "1",
        "steps": [
            {"id": "o", "call": "get_order", "with": {"order_id": 502}},
            {"id": "r", "call": "issue_refund",
             "with": {"order_id": {"$ref": "o.id"}, "amount": 50.0}},
        ],
    }
    verified, errors = _verify(plan)
    assert errors == []
    assert verified.single_call is False
    assert len(verified.steps) == 2
    assert verified.dependency_order == ("o", "r")


# ---------------------------------------------------------------------------
# Capability resolution
# ---------------------------------------------------------------------------

def test_unknown_capability():
    verified, errors = _verify({"call": "does_not_exist", "with": {}})
    assert verified is None
    assert len(errors) == 1
    assert errors[0].code == "UNKNOWN_CAPABILITY"
    assert "does_not_exist" in errors[0].message


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

def test_missing_required_arg():
    verified, errors = _verify({"call": "get_order", "with": {}})
    assert verified is None
    assert any("missing required" in e.message for e in errors)


def test_unknown_arg():
    verified, errors = _verify({
        "call": "get_order",
        "with": {"order_id": 1, "evil": "payload"},
    })
    assert verified is None
    assert any("unknown argument" in e.message for e in errors)


def test_wrong_arg_type():
    verified, errors = _verify({
        "call": "get_order",
        "with": {"order_id": "not-an-int"},
    })
    assert verified is None
    assert any(e.code == "SCHEMA_VALIDATION_FAILED" for e in errors)


def test_bool_not_int_at_verifier():
    verified, errors = _verify({
        "call": "get_order",
        "with": {"order_id": True},
    })
    assert verified is None
    assert any(e.code == "SCHEMA_VALIDATION_FAILED" for e in errors)


# ---------------------------------------------------------------------------
# Reference type checking
# ---------------------------------------------------------------------------

def test_ref_type_mismatch_rejected():
    # get_order returns dict[str, int], so $ref "o.id" is int.
    # issue_refund.amount is float. int is NOT assignable to float.
    plan = {
        "version": "1",
        "steps": [
            {"id": "o", "call": "get_order", "with": {"order_id": 1}},
            {"id": "r", "call": "issue_refund",
             "with": {"order_id": {"$ref": "o.id"},
                      "amount": {"$ref": "o.id"}}},  # int into float slot
        ],
    }
    verified, errors = _verify(plan)
    assert verified is None
    assert any(e.code == "INVALID_REFERENCE" for e in errors)


def test_ref_to_untyped_output_rejected():
    # no_output has no declared output schema -> cannot $ref into it.
    plan = {
        "version": "1",
        "steps": [
            {"id": "src", "call": "no_output", "with": {"x": 1}},
            {"id": "dst", "call": "get_order",
             "with": {"order_id": {"$ref": "src"}}},
        ],
    }
    verified, errors = _verify(plan)
    assert verified is None
    assert any(
        e.code == "INVALID_REFERENCE" and "no declared output schema" in e.message
        for e in errors
    )


def test_ref_missing_path():
    # get_order returns dict[str, int]; any string key is valid on a dict,
    # but descending *into* an int value is not.
    plan = {
        "version": "1",
        "steps": [
            {"id": "o", "call": "get_order", "with": {"order_id": 1}},
            {"id": "r", "call": "issue_refund",
             "with": {"order_id": {"$ref": "o.id.wrong"},
                      "amount": 5.0}},
        ],
    }
    verified, errors = _verify(plan)
    assert verified is None
    assert any(e.code == "INVALID_REFERENCE" for e in errors)


# ---------------------------------------------------------------------------
# Input shape
# ---------------------------------------------------------------------------

def test_non_canonical_plan_rejected():
    verified, errors = verify_plan(
        {"call": "get_order", "with": {"order_id": 1}},
        registry=_registry(),
        limits=DEFAULT_LIMITS,
    )
    assert verified is None
    assert len(errors) == 1
    assert errors[0].code == "INVALID_PLAN"


# ---------------------------------------------------------------------------
# Verification metadata
# ---------------------------------------------------------------------------

def test_snapshot_hash_is_recorded():
    reg = _registry()
    verified, errors = _verify(
        {"call": "get_order", "with": {"order_id": 1}}, reg=reg,
    )
    assert errors == []
    assert verified.capability_snapshot_hash == reg.snapshot_hash()


def test_verification_hash_is_deterministic():
    reg = _registry()
    v1, _ = _verify({"call": "get_order", "with": {"order_id": 1}}, reg=reg)
    v2, _ = _verify({"call": "get_order", "with": {"order_id": 1}}, reg=reg)
    assert v1.verification_hash == v2.verification_hash


def test_verification_hash_changes_on_plan_change():
    reg = _registry()
    v1, _ = _verify({"call": "get_order", "with": {"order_id": 1}}, reg=reg)
    v2, _ = _verify({"call": "get_order", "with": {"order_id": 2}}, reg=reg)
    assert v1.verification_hash != v2.verification_hash


def test_verified_plan_is_frozen():
    verified, _ = _verify({"call": "get_order", "with": {"order_id": 1}})
    with pytest.raises(Exception):  # FrozenInstanceError from dataclasses
        verified.single_call = False  # type: ignore[misc]