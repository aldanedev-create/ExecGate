"""
Result and error object invariants.

``Result``/``VerificationReport`` enforce consistency at construction
time, so tests that would violate their invariants fail loudly rather
than silently producing malformed outcomes. ``Error`` codes are checked
against the stable taxonomy at construction time.
"""

from __future__ import annotations

import json

import pytest

from logiq import Error, Result, VerificationReport
from logiq.errors import (
    ALL_CODES,
    INVALID_PLAN,
    OUTPUT_VALIDATION_FAILED,
    POLICY_REJECTED,
    SCHEMA_VALIDATION_FAILED,
)
from logiq.ir import VerifiedStep, _construct_verified_plan
from logiq.results import StepTrace, Trace


def _real_verified_plan():
    return _construct_verified_plan(
        plan_version="1",
        steps=(VerifiedStep(id="s", capability="c", arguments={}),),
        dependency_order=("s",),
        capability_snapshot_hash="h",
        verification_hash="h",
        single_call=False,
    )


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

def test_error_accepts_valid_code():
    e = Error(code=INVALID_PLAN, message="x")
    assert e.code == INVALID_PLAN


def test_error_rejects_unknown_code():
    with pytest.raises(ValueError, match="unknown error code"):
        Error(code="NOT_A_REAL_CODE", message="x")


def test_error_all_taxonomy_codes_valid():
    for code in ALL_CODES:
        Error(code=code, message="m")  # must not raise


def test_error_to_dict():
    e = Error(code=POLICY_REJECTED, message="m", path="p", details={"k": "v"})
    d = e.to_dict()
    assert d == {
        "code": POLICY_REJECTED,
        "message": "m",
        "path": "p",
        "details": {"k": "v"},
    }


def test_error_path_optional():
    e = Error(code=INVALID_PLAN, message="m")
    assert e.path is None
    assert e.to_dict()["path"] is None


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

def test_result_ok_with_errors_rejected():
    e = Error(code=INVALID_PLAN, message="m")
    with pytest.raises(ValueError, match="ok=True must have no errors"):
        Result(ok=True, errors=(e,))


def test_result_failure_without_errors_rejected():
    with pytest.raises(ValueError, match="at least one error"):
        Result(ok=False, errors=())


def test_result_success_factory():
    r = Result.success(42)
    assert r.ok is True
    assert r.value == 42
    assert r.errors == ()


def test_result_failure_factory():
    e = Error(code=SCHEMA_VALIDATION_FAILED, message="m")
    r = Result.failure([e])
    assert r.ok is False
    assert r.value is None
    assert r.errors == (e,)


def test_result_failure_factory_empty_errors_rejected():
    with pytest.raises(ValueError, match="at least one error"):
        Result.failure([])


def test_result_to_dict_json_safe():
    r = Result.success({"x": 1})
    # Must not raise — no non-JSON-serializable values.
    json.dumps(r.to_dict())


def test_result_to_dict_includes_errors():
    e = Error(code=OUTPUT_VALIDATION_FAILED, message="m")
    r = Result.failure([e])
    d = r.to_dict()
    assert d["ok"] is False
    assert d["value"] is None
    assert d["errors"][0]["code"] == OUTPUT_VALIDATION_FAILED


# ---------------------------------------------------------------------------
# VerificationReport
# ---------------------------------------------------------------------------

def test_report_ok_without_verified_plan_rejected():
    with pytest.raises(ValueError, match="must carry a VerifiedPlan"):
        VerificationReport(ok=True)


def test_report_failure_with_verified_plan_rejected():
    vp = _real_verified_plan()
    e = Error(code=INVALID_PLAN, message="m")
    with pytest.raises(ValueError, match="must not carry a VerifiedPlan"):
        VerificationReport(ok=False, verified_plan=vp, errors=(e,))


def test_report_failure_without_errors_rejected():
    with pytest.raises(ValueError, match="at least one error"):
        VerificationReport(ok=False)


def test_report_success_factory():
    vp = _real_verified_plan()
    report = VerificationReport.success(vp)
    assert report.ok is True
    assert report.verified_plan is vp
    assert report.errors == ()


def test_report_failure_factory():
    e = Error(code=SCHEMA_VALIDATION_FAILED, message="m")
    report = VerificationReport.failure([e])
    assert report.ok is False
    assert report.verified_plan is None
    assert report.errors == (e,)


def test_report_to_dict():
    vp = _real_verified_plan()
    report = VerificationReport.success(vp)
    d = report.to_dict()
    assert d["ok"] is True
    assert d["errors"] == []
    assert d["verified_plan"]["plan_version"] == "1"


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------

def test_trace_to_dict():
    trace = Trace(
        execution_id="abc",
        plan_version="1",
        verification_duration_ms=1.5,
        steps=(
            StepTrace(step_id="s", capability="c", status="ok", duration_ms=0.5),
        ),
    )
    d = trace.to_dict()
    assert d["execution_id"] == "abc"
    assert d["plan_version"] == "1"
    assert len(d["steps"]) == 1
    assert d["steps"][0]["step_id"] == "s"
    assert d["steps"][0]["capability"] == "c"


def test_trace_empty_steps():
    trace = Trace(execution_id="x", plan_version="1", verification_duration_ms=0.0)
    d = trace.to_dict()
    assert d["steps"] == []


def test_step_trace_with_error_code():
    st = StepTrace(
        step_id="s",
        capability="c",
        status="failed",
        duration_ms=2.0,
        error_code="HANDLER_FAILED",
    )
    assert st.to_dict()["error_code"] == "HANDLER_FAILED"