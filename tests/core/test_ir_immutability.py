"""
The verified intermediate representation.

``VerifiedPlan`` is frozen, unforgeable from user code, and its
arguments are recursively frozen. These properties are what make the
executor's ``isinstance`` check structurally meaningful — a plan that
merely *claims* to be verified cannot satisfy it.

Tests here deliberately use the private ``_construct_verified_plan``
because the whole point is to assert that the *public* constructor does
not exist and cannot be coerced into producing a ``VerifiedPlan``.
"""

from __future__ import annotations

import dataclasses

import pytest

from logiq.ir import VerifiedPlan, VerifiedStep, _construct_verified_plan


def _make_plan(**overrides):
    base = dict(
        plan_version="1",
        steps=(VerifiedStep(id="s1", capability="c", arguments={"a": 1}),),
        dependency_order=("s1",),
        capability_snapshot_hash="snap",
        verification_hash="vh",
        single_call=False,
    )
    base.update(overrides)
    return _construct_verified_plan(**base)


# ---------------------------------------------------------------------------
# Structural properties
# ---------------------------------------------------------------------------


def test_verified_plan_is_a_frozen_dataclass():
    assert dataclasses.is_dataclass(VerifiedPlan)
    params = VerifiedPlan.__dataclass_params__  # type: ignore[attr-defined]
    assert params.frozen is True
    assert params.init is False


def test_verified_step_is_a_frozen_dataclass():
    assert dataclasses.is_dataclass(VerifiedStep)
    params = VerifiedStep.__dataclass_params__  # type: ignore[attr-defined]
    assert params.frozen is True


# ---------------------------------------------------------------------------
# Unforgeable from user code
# ---------------------------------------------------------------------------


def test_direct_construction_raises_type_error():
    # @dataclass(init=False) means no __init__ is generated. Calling the
    # class raises TypeError, not a silently malformed object.
    with pytest.raises(TypeError):
        VerifiedPlan(  # type: ignore[call-arg]
            plan_version="1",
            steps=(),
            dependency_order=(),
            capability_snapshot_hash="x",
            verification_hash="x",
            single_call=False,
        )


def test_object_new_bypass_has_no_fields():
    # object.__new__ produces an empty instance; no attribute access
    # succeeds without the private constructor.
    vp = object.__new__(VerifiedPlan)
    with pytest.raises(AttributeError):
        _ = vp.single_call  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Mutation rejected
# ---------------------------------------------------------------------------


def test_verified_plan_frozen():
    vp = _make_plan()
    with pytest.raises(dataclasses.FrozenInstanceError):
        vp.single_call = True  # type: ignore[misc]

    with pytest.raises(dataclasses.FrozenInstanceError):
        vp.verification_hash = "changed"  # type: ignore[misc]


def test_verified_step_frozen():
    step = VerifiedStep(id="x", capability="c", arguments={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        step.id = "y"  # type: ignore[misc]


def test_verified_step_arguments_are_frozen():
    from types import MappingProxyType

    step = VerifiedStep(id="x", capability="c", arguments={"a": 1})
    assert isinstance(step.arguments, MappingProxyType)
    with pytest.raises(TypeError):
        step.arguments["a"] = 2  # type: ignore[index]


def test_verified_step_arguments_dict_copied():
    # The original dict cannot be mutated to affect the step.
    original = {"a": 1}
    step = VerifiedStep(id="x", capability="c", arguments=original)
    original["a"] = 999
    assert step.arguments["a"] == 1


# ---------------------------------------------------------------------------
# single_call field
# ---------------------------------------------------------------------------


def test_single_call_recorded():
    vp = _make_plan(single_call=True)
    assert vp.single_call is True

    vp = _make_plan(single_call=False)
    assert vp.single_call is False


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_serialize_round_trips_fields():
    vp = _make_plan(single_call=True)
    d = vp.serialize()

    assert d["plan_version"] == "1"
    assert d["single_call"] is True
    assert d["dependency_order"] == ["s1"]
    assert d["capability_snapshot_hash"] == "snap"
    assert d["verification_hash"] == "vh"
    assert d["steps"] == [{"id": "s1", "call": "c", "with": {"a": 1}}]


def test_serialize_is_json_compatible():
    import json

    vp = _make_plan()
    json.dumps(vp.serialize())  # must not raise
