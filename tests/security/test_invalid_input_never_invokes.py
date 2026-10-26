"""
Invalid arguments never reach a handler.

Schema validation runs before the handler is invoked. Every failure mode
(missing, wrong type, wrong shape, extra field, out-of-range) must reject
before any side effect occurs.
"""

from __future__ import annotations

from typing import Annotated

import pytest

from logiq import Logix
from logiq.schemas import Gt, Le


def _spy(logix):
    """Register a handler with one int arg that records invocation."""
    invoked: list[int] = []

    @logix.capability
    def op(x: int) -> int:
        invoked.append(x)
        return x

    return invoked


@pytest.mark.security
@pytest.mark.parametrize("bad_args", [
    {},                                  # missing required
    {"x": "not an int"},                 # wrong type
    {"x": 1.5},                          # float for int
    {"x": True},                         # bool is not int
    {"x": None},                         # None for non-optional
    {"x": 1, "extra": "payload"},        # unknown field
    {"x": [1, 2]},                       # list for int
    {"x": {"a": 1}},                     # dict for int
])
def test_invalid_input_does_not_invoke(logix, bad_args):
    invoked = _spy(logix)
    result = logix.run({"call": "op", "with": bad_args})
    assert not result.ok
    assert result.errors[0].code in {
        "SCHEMA_VALIDATION_FAILED",
        "INVALID_PLAN",  # possible if args are malformed at parse level
    }
    assert invoked == []


@pytest.mark.security
def test_constraint_violation_does_not_invoke(logix):
    invoked: list[int] = []

    @logix.capability
    def bounded(x: Annotated[int, Gt(0), Le(100)]) -> int:
        invoked.append(x)
        return x

    for value in (0, -1, 101):
        result = logix.run({"call": "bounded", "with": {"x": value}})
        assert not result.ok
        assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"
    assert invoked == []


@pytest.mark.security
def test_non_dict_arguments_does_not_invoke(logix):
    invoked = _spy(logix)
    result = logix.run({"call": "op", "with": "not-a-dict"})
    assert not result.ok
    assert invoked == []


@pytest.mark.security
def test_valid_input_does_invoke(logix):
    """Sanity: the same handler does run on valid input."""
    invoked = _spy(logix)
    result = logix.run({"call": "op", "with": {"x": 5}})
    assert result.ok
    assert invoked == [5]