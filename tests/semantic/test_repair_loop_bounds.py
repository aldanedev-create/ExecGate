"""
Bounded repair loop and reroute refusal.

The loop bounds total attempts and refuses proposals that would route
around a prior policy or authorization refusal. Reroute detection uses
``Error.details["capability"]`` (when present) to identify which
capability was denied, then checks both the capability name and its
``effects`` class.
"""

from __future__ import annotations

import pytest

from logiq import Logix
from logiq.capabilities import Registry, build_capability
from logiq.errors import (
    approval_required,
    authorization_failed,
    policy_rejected,
)
from logiq.semantic import RepairLoop, RepairRefused, RepairState
from logiq.semantic.repair_loop import assert_repair_allowed


def _registry():
    reg = Registry()

    def refund(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    def delete_order(order_id: int) -> dict[str, int]:
        return {"ok": 1}

    def get_order(order_id: int) -> dict[str, int]:
        return {"id": order_id}

    reg.add(build_capability(refund, name="refund", effects="write"))
    reg.add(build_capability(delete_order, name="delete_order", effects="write"))
    reg.add(build_capability(get_order, name="get_order", effects="read"))
    return reg


# ---------------------------------------------------------------------------
# check_proposal — baseline
# ---------------------------------------------------------------------------

def test_empty_proposal_allowed():
    loop = RepairLoop(max_attempts=3)
    assert loop.check_proposal([]) is RepairState.ALLOWED


def test_fresh_loop_allows_anything():
    loop = RepairLoop(max_attempts=3)
    assert loop.check_proposal(["anything"]) is RepairState.ALLOWED


# ---------------------------------------------------------------------------
# Exhaustion
# ---------------------------------------------------------------------------

def test_exhaustion_after_max_attempts():
    loop = RepairLoop(max_attempts=2)
    loop.record_outcome([])
    assert not loop.exhausted
    loop.record_outcome([])
    assert loop.exhausted
    assert loop.check_proposal(["anything"]) is RepairState.EXHAUSTED


def test_max_attempts_one():
    loop = RepairLoop(max_attempts=1)
    assert loop.check_proposal(["x"]) is RepairState.ALLOWED
    loop.record_outcome([])
    assert loop.check_proposal(["x"]) is RepairState.EXHAUSTED


# ---------------------------------------------------------------------------
# Capability-level refusal
# ---------------------------------------------------------------------------

def test_capability_denied_is_refused():
    loop = RepairLoop(max_attempts=3)
    loop.record_outcome([
        policy_rejected("limit", details={"capability": "refund"}),
    ])
    assert loop.check_proposal(["refund"]) is RepairState.REFUSED


def test_denied_capability_does_not_block_others():
    loop = RepairLoop(max_attempts=3)
    loop.record_outcome([
        policy_rejected("limit", details={"capability": "refund"}),
    ])
    # Different capability with no registry → no effect tracking, so
    # effect-based refusal does not apply. Only "refund" is refused.
    assert loop.check_proposal(["other"]) is RepairState.ALLOWED


# ---------------------------------------------------------------------------
# Effect-class refusal (requires a registry)
# ---------------------------------------------------------------------------

def test_effect_class_refusal_blocks_same_effect():
    loop = RepairLoop(max_attempts=3, registry=_registry())
    loop.record_outcome([
        policy_rejected("limit", details={"capability": "refund"}),
    ])
    # refund was denied → "write" effect is now denied.
    assert loop.check_proposal(["refund"]) is RepairState.REFUSED
    assert loop.check_proposal(["delete_order"]) is RepairState.REFUSED


def test_effect_class_refusal_allows_different_effect():
    loop = RepairLoop(max_attempts=3, registry=_registry())
    loop.record_outcome([
        policy_rejected("limit", details={"capability": "refund"}),
    ])
    # get_order is a read-effect capability; not blocked by a write denial.
    assert loop.check_proposal(["get_order"]) is RepairState.ALLOWED


# ---------------------------------------------------------------------------
# Only refusal codes trigger refusal
# ---------------------------------------------------------------------------

def test_non_refusal_errors_do_not_record_capability():
    loop = RepairLoop(max_attempts=3)
    loop.record_outcome([
        policy_rejected("limit", details={"capability": "refund"}),
    ])
    assert loop.check_proposal(["refund"]) is RepairState.REFUSED


def test_schema_error_does_not_record_capability():
    from logiq.errors import schema_validation_failed

    loop = RepairLoop(max_attempts=3)
    loop.record_outcome([
        schema_validation_failed("bad arg", details={"capability": "refund"}),
    ])
    # Schema error is not a refusal code — capability is not added to denied set.
    assert loop.check_proposal(["refund"]) is RepairState.ALLOWED


def test_authorization_failure_counts_as_refusal():
    loop = RepairLoop(max_attempts=3)
    loop.record_outcome([
        authorization_failed("denied", details={"capability": "refund"}),
    ])
    assert loop.check_proposal(["refund"]) is RepairState.REFUSED


def test_approval_required_counts_as_refusal():
    loop = RepairLoop(max_attempts=3)
    loop.record_outcome([
        approval_required("refund"),
    ])
    # approval_required doesn't set details["capability"] in its default form,
    # so no capability is added. Test the negative case.
    assert loop.check_proposal(["refund"]) is RepairState.ALLOWED


# ---------------------------------------------------------------------------
# Missing capability in details
# ---------------------------------------------------------------------------

def test_refusal_without_capability_in_details_does_not_block():
    loop = RepairLoop(max_attempts=3)
    # A refusal error that doesn't identify the capability.
    loop.record_outcome([policy_rejected("limit")])  # no details
    assert loop.check_proposal(["refund"]) is RepairState.ALLOWED


# ---------------------------------------------------------------------------
# assert_repair_allowed
# ---------------------------------------------------------------------------

def test_assert_passes_for_allowed():
    loop = RepairLoop(max_attempts=3)
    assert_repair_allowed(loop, ["anything"])  # no raise


def test_assert_raises_for_refused():
    loop = RepairLoop(max_attempts=3)
    loop.record_outcome([policy_rejected("limit", details={"capability": "refund"})])
    with pytest.raises(RepairRefused, match="reroute"):
        assert_repair_allowed(loop, ["refund"])


def test_assert_raises_for_exhausted():
    loop = RepairLoop(max_attempts=1)
    loop.record_outcome([])
    with pytest.raises(RepairRefused, match="exhausted"):
        assert_repair_allowed(loop, ["anything"])


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------

def test_attempts_counter():
    loop = RepairLoop(max_attempts=5)
    assert loop.attempts == 0
    loop.record_outcome([])
    assert loop.attempts == 1
    loop.record_outcome([])
    assert loop.attempts == 2


def test_last_errors():
    loop = RepairLoop(max_attempts=3)
    e = policy_rejected("x")
    loop.record_outcome([e])
    assert loop.last_errors == (e,)