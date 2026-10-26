"""
Output validation in the executor.

A handler's return value is validated against its declared output
schema. When no output schema is declared (unannotated return), any
value passes.
"""

from __future__ import annotations

import pytest

from logiq import Logix


# ---------------------------------------------------------------------------
# Matching output
# ---------------------------------------------------------------------------

def test_matching_int_output(logix):
    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    result = logix.run({"call": "add", "with": {"a": 1, "b": 2}})
    assert result.ok
    assert result.value == 3


def test_matching_dict_output(logix):
    @logix.capability
    def get_order(order_id: int) -> dict[str, int]:
        return {"id": order_id}

    result = logix.run({"call": "get_order", "with": {"order_id": 5}})
    assert result.ok
    assert result.value == {"id": 5}


def test_matching_none_output(logix):
    @logix.capability
    def noop(x: int) -> None:
        return None

    result = logix.run({"call": "noop", "with": {"x": 1}})
    assert result.ok
    assert result.value is None


# ---------------------------------------------------------------------------
# Mismatched output
# ---------------------------------------------------------------------------

def test_mismatched_output_rejected(logix):
    @logix.capability
    def bad(x: int) -> int:
        return "not an int"  # type: ignore[return-value]

    result = logix.run({"call": "bad", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "OUTPUT_VALIDATION_FAILED"


def test_wrong_dict_shape_rejected(logix):
    @logix.capability
    def bad(order_id: int) -> dict[str, int]:
        return {"id": "not an int"}  # type: ignore[dict-item]

    result = logix.run({"call": "bad", "with": {"order_id": 1}})
    assert not result.ok
    assert result.errors[0].code == "OUTPUT_VALIDATION_FAILED"


def test_bool_is_not_int_in_output(logix):
    """Same strict semantics apply to output validation."""
    @logix.capability
    def bad(x: int) -> int:
        return True  # type: ignore[return-value]

    result = logix.run({"call": "bad", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "OUTPUT_VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# No output schema declared
# ---------------------------------------------------------------------------

def test_no_return_annotation_skips_output_validation(logix):
    @logix.capability
    def f(x: int):
        return "anything goes"

    result = logix.run({"call": "f", "with": {"x": 1}})
    assert result.ok
    assert result.value == "anything goes"


# ---------------------------------------------------------------------------
# Handler raises
# ---------------------------------------------------------------------------

def test_handler_exception_produces_handler_failed(logix):
    @logix.capability
    def fail(x: int) -> int:
        raise ValueError("boom")

    result = logix.run({"call": "fail", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "HANDLER_FAILED"