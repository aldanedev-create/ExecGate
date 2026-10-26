"""
Output validation failures are reported correctly.

A handler whose return value does not match its declared output schema
must produce ``OUTPUT_VALIDATION_FAILED``. The handler *did* run (so
side effects may have occurred); the failure is that the output is not
what was promised.
"""

from __future__ import annotations

import pytest


@pytest.mark.security
def test_wrong_type_output_reported(logix):
    @logix.capability
    def bad(x: int) -> int:
        return "not an int"  # type: ignore[return-value]

    result = logix.run({"call": "bad", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "OUTPUT_VALIDATION_FAILED"


@pytest.mark.security
def test_wrong_dict_shape_output_reported(logix):
    @logix.capability
    def bad(x: int) -> dict[str, int]:
        return {"id": "not an int"}  # type: ignore[dict-item]

    result = logix.run({"call": "bad", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "OUTPUT_VALIDATION_FAILED"


@pytest.mark.security
def test_bool_rejected_as_int_output(logix):
    """Strict types apply to output validation too."""

    @logix.capability
    def bad(x: int) -> int:
        return True  # type: ignore[return-value]

    result = logix.run({"call": "bad", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "OUTPUT_VALIDATION_FAILED"


@pytest.mark.security
def test_output_failure_marks_handler_as_ran(logix):
    """Confirms the handler executed — the failure is post-execution, so
    callers know side effects may have occurred."""
    ran = []

    @logix.capability
    def bad(x: int) -> int:
        ran.append(1)
        return "wrong"  # type: ignore[return-value]

    result = logix.run({"call": "bad", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "OUTPUT_VALIDATION_FAILED"
    assert ran == [1]  # handler did run


@pytest.mark.security
def test_output_failure_reported_in_trace(logix):
    @logix.capability
    def bad(x: int) -> int:
        return "wrong"  # type: ignore[return-value]

    result = logix.run({"call": "bad", "with": {"x": 1}})
    assert result.trace is not None
    assert result.trace.steps[0].status == "failed"
    assert result.trace.steps[0].error_code == "OUTPUT_VALIDATION_FAILED"


@pytest.mark.security
def test_output_failure_is_distinct_from_handler_failure(logix):
    """OUTPUT_VALIDATION_FAILED and HANDLER_FAILED are different codes —
    callers can distinguish 'ran and returned wrong shape' from 'crashed'."""

    @logix.capability
    def crashes(x: int) -> int:
        raise ValueError("boom")

    @logix.capability
    def wrong_shape(x: int) -> int:
        return "wrong"  # type: ignore[return-value]

    r1 = logix.run({"call": "crashes", "with": {"x": 1}})
    r2 = logix.run({"call": "wrong_shape", "with": {"x": 1}})

    assert r1.errors[0].code == "HANDLER_FAILED"
    assert r2.errors[0].code == "OUTPUT_VALIDATION_FAILED"


@pytest.mark.security
def test_output_failure_does_not_leak_raw_output(logix):
    """The framework's default error message mentions the schema issue
    but does not embed the raw (possibly sensitive) return value."""
    sensitive_return = "SECRET-PII-1234"

    @logix.capability
    def leaky(x: int) -> int:
        return sensitive_return  # type: ignore[return-value]

    result = logix.run({"call": "leaky", "with": {"x": 1}})
    assert not result.ok
    message = result.errors[0].message
    # The framework reports the schema mismatch, not the raw value.
    assert sensitive_return not in message
