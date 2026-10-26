"""
Native constraints via ``typing.Annotated``.

Tests ``Gt``, ``Ge``, ``Lt``, ``Le``, ``MinLength``, ``MaxLength``,
``Pattern`` through the ``ConstrainedType`` wrapper.
"""

from __future__ import annotations

from typing import Annotated

import pytest

from logiq.annotation_inspect import inspect_capability
from logiq.schemas import (
    Ge,
    Gt,
    Le,
    Lt,
    MaxLength,
    MinLength,
    Pattern,
    SchemaInferenceError,
    infer_input_schema,
)
from logiq.schemas.validate import ConstrainedType


def _schema(fn):
    return infer_input_schema(inspect_capability(fn).parameters)


# ---------------------------------------------------------------------------
# Numeric bounds
# ---------------------------------------------------------------------------

def test_gt_constraint():
    def f(x: Annotated[int, Gt(0)]) -> int:
        return x

    schema = _schema(f)
    field = schema.fields["x"]
    assert isinstance(field, ConstrainedType)
    assert field.validate(1) == []
    assert field.validate(0) != []
    assert field.validate(-1) != []


def test_ge_constraint():
    def f(x: Annotated[int, Ge(0)]) -> int:
        return x

    field = _schema(f).fields["x"]
    assert field.validate(0) == []
    assert field.validate(-1) != []


def test_lt_constraint():
    def f(x: Annotated[int, Lt(10)]) -> int:
        return x

    field = _schema(f).fields["x"]
    assert field.validate(9) == []
    assert field.validate(10) != []


def test_le_constraint():
    def f(x: Annotated[int, Le(10)]) -> int:
        return x

    field = _schema(f).fields["x"]
    assert field.validate(10) == []
    assert field.validate(11) != []


def test_multiple_bounds():
    def f(x: Annotated[int, Gt(0), Le(100)]) -> int:
        return x

    field = _schema(f).fields["x"]
    assert field.validate(50) == []
    assert field.validate(0) != []
    assert field.validate(101) != []


# ---------------------------------------------------------------------------
# String constraints
# ---------------------------------------------------------------------------

def test_min_length():
    def f(s: Annotated[str, MinLength(3)]) -> str:
        return s

    field = _schema(f).fields["s"]
    assert field.validate("abc") == []
    assert field.validate("ab") != []


def test_max_length():
    def f(s: Annotated[str, MaxLength(5)]) -> str:
        return s

    field = _schema(f).fields["s"]
    assert field.validate("abc") == []
    assert field.validate("abcdef") != []


def test_pattern():
    def f(s: Annotated[str, Pattern(r"[a-z]+")]) -> str:
        return s

    field = _schema(f).fields["s"]
    assert field.validate("abc") == []
    assert field.validate("ABC") != []
    assert field.validate("abc1") != []


# ---------------------------------------------------------------------------
# JSON Schema output
# ---------------------------------------------------------------------------

def test_constraint_appears_in_json_schema():
    def f(x: Annotated[int, Gt(0), Le(100)]) -> int:
        return x

    schema = _schema(f)
    js = schema.fields["x"].to_json_schema()
    assert js["type"] == "integer"
    assert js["exclusiveMinimum"] == 0
    assert js["maximum"] == 100


def test_min_length_in_json_schema():
    def f(s: Annotated[str, MinLength(3)]) -> str:
        return s

    js = _schema(f).fields["s"].to_json_schema()
    assert js["minLength"] == 3


# ---------------------------------------------------------------------------
# Rejection
# ---------------------------------------------------------------------------

class MyConstraint:
    """Module-level so ``get_type_hints`` can resolve it (stringified annotations)."""


def test_unsupported_constraint_raises():
    def f(x: Annotated[int, MyConstraint()]) -> int:  # type: ignore[valid-type]
        return x

    with pytest.raises(SchemaInferenceError, match="unsupported constraint"):
        _schema(f)


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------

def test_constraint_enforced_at_runtime(logix):
    @logix.capability
    def create_user(age: Annotated[int, Gt(0), Le(150)]) -> str:
        return "ok"

    # Valid
    assert logix.run({"call": "create_user", "with": {"age": 30}}).ok

    # Rejected: violates Le(150)
    result = logix.run({"call": "create_user", "with": {"age": 200}})
    assert not result.ok
    assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"

    # Rejected: violates Gt(0)
    result = logix.run({"call": "create_user", "with": {"age": 0}})
    assert not result.ok