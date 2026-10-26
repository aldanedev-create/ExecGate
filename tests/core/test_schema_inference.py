"""
Schema inference from Python annotations.

Tests ``inspect_capability`` + ``infer_input_schema`` +
``infer_output_schema``.

Known gap (0.1.0): bare ``dict`` and bare ``list`` are not yet supported
by ``describe_unsupported`` — they surface as ``unsupported annotation``.
Use ``dict[str, X]`` / ``list[X]`` in tests and in capabilities. The
README's ``-> dict:`` example does not yet work end-to-end.
"""

from __future__ import annotations

import typing

import pytest

from execgate.annotation_inspect import inspect_capability
from execgate.schemas import (
    BoolType,
    DictType,
    IntType,
    ListType,
    LiteralType,
    NoneType,
    SchemaInferenceError,
    StrType,
    UnionType,
    infer_input_schema,
    infer_output_schema,
)


def _infer(fn):
    info = inspect_capability(fn)
    return (
        infer_input_schema(info.parameters),
        infer_output_schema(info.return_annotation),
    )


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


def test_simple_int_parameters():
    def add(a: int, b: int) -> int:
        return a + b

    inp, out = _infer(add)
    assert inp.fields["a"] == IntType()
    assert inp.fields["b"] == IntType()
    assert inp.required == frozenset({"a", "b"})
    assert out == IntType()


def test_default_makes_parameter_optional():
    def f(a: int, b: str = "x") -> int:
        return a

    inp, _ = _infer(f)
    assert "a" in inp.required
    assert "b" not in inp.required


def test_optional_parameter():
    def f(x: int | None = None) -> int:
        return 0

    inp, _ = _infer(f)
    # Optional[int] -> UnionType(IntType(), NoneType())
    schema = inp.fields["x"]
    assert isinstance(schema, UnionType)
    assert IntType() in schema.members
    assert NoneType() in schema.members
    assert "x" not in inp.required  # has default


def test_optional_with_non_none_default():
    def f(x: int | None = 5) -> int:
        return 0

    inp, _ = _infer(f)
    assert isinstance(inp.fields["x"], UnionType)
    assert "x" not in inp.required


def test_list_of_int():
    def f(xs: list[int]) -> int:
        return 0

    inp, _ = _infer(f)
    assert inp.fields["xs"] == ListType(item_type=IntType())


def test_dict_of_int():
    def f(m: dict[str, int]) -> int:
        return 0

    inp, _ = _infer(f)
    assert inp.fields["m"] == DictType(value_type=IntType())


def test_nested_list_of_dicts():
    def f(items: list[dict[str, int]]) -> int:
        return 0

    inp, _ = _infer(f)
    assert inp.fields["items"] == ListType(item_type=DictType(value_type=IntType()))


def test_literal():
    def f(kind: typing.Literal["a", "b"]) -> int:
        return 0

    inp, _ = _infer(f)
    assert inp.fields["kind"] == LiteralType(values=("a", "b"))


def test_dict_with_any_value_rejected():
    """typing.Any is not a validation contract (ADR-0003)."""

    def f(m: dict[str, typing.Any]) -> int:
        return 0

    with pytest.raises(SchemaInferenceError):
        _infer(f)


def test_unsupported_set_annotation():
    def f(x: set) -> int:
        return 0

    with pytest.raises(SchemaInferenceError, match="unsupported annotation"):
        _infer(f)


def test_unannotated_parameter_raises():
    def f(x) -> int:
        return 0

    with pytest.raises(SchemaInferenceError, match="missing annotation"):
        _infer(f)


# ---------------------------------------------------------------------------
# Return schemas
# ---------------------------------------------------------------------------


def test_no_return_annotation_yields_none():
    def f(x: int):
        return x

    _, out = _infer(f)
    assert out is None


def test_explicit_none_return():
    def f(x: int) -> None:
        return None

    _, out = _infer(f)
    assert out == NoneType()


def test_bool_return():
    def f(x: int) -> bool:
        return True

    _, out = _infer(f)
    assert out == BoolType()


def test_str_return():
    def f(x: int) -> str:
        return "y"

    _, out = _infer(f)
    assert out == StrType()


def test_unsupported_return_annotation():
    def f(x: int) -> set:
        return set()

    info = inspect_capability(f)
    with pytest.raises(SchemaInferenceError):
        infer_output_schema(info.return_annotation)


# ---------------------------------------------------------------------------
# Nullable mismatch
# ---------------------------------------------------------------------------


def test_default_none_without_optional_rejected():
    # Default is None, but annotation is int (not Optional[int]).
    # This is rejected: the default does not match the schema.
    def f(x: int = None) -> int:  # type: ignore[assignment]  # noqa: RUF013
        return 0

    with pytest.raises(SchemaInferenceError, match="does not allow None"):
        _infer(f)
