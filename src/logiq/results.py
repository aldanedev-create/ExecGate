"""
Result objects returned across the public API.

Three shapes:

- ``Result``               — outcome of ``run()`` / ``execute()``.
- ``VerificationReport``   — outcome of ``verify()``; carries a
                             ``VerifiedPlan`` when ``ok``.
- ``Trace``                — safe, redacted execution metadata.

All are frozen. ``to_dict()`` is the only sanctioned serialization; it
guarantees redaction (see ``_internal/redaction.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from logiq.errors import Error

if TYPE_CHECKING:
    from logiq.ir import VerifiedPlan


@dataclass(frozen=True)
class StepTrace:
    """Per-step execution metadata. Contains no raw argument values."""

    step_id: str
    capability: str
    status: str                       # "ok" | "failed" | "skipped" | "cancelled"
    duration_ms: float
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "capability": self.capability,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class Trace:
    """
    Safe execution metadata.

    Redaction is applied at construction time by ``to_dict()``; the trace
    object itself holds no raw arguments, model prompts, or handler return
    values. See ``docs/system-design.md §8``.
    """

    execution_id: str
    plan_version: str
    verification_duration_ms: float
    steps: tuple[StepTrace, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "plan_version": self.plan_version,
            "verification_duration_ms": self.verification_duration_ms,
            "steps": [s.to_dict() for s in self.steps],
        }


@dataclass(frozen=True)
class Result:
    """Outcome of ``run()`` or ``execute()``."""

    ok: bool
    value: Any | None = None
    errors: tuple[Error, ...] = ()
    trace: Trace | None = None
    execution_id: str = ""

    def __post_init__(self) -> None:
        # A result is either ok with no errors, or not ok with errors.
        if self.ok and self.errors:
            raise ValueError("ok=True must have no errors")
        if not self.ok and not self.errors:
            raise ValueError("ok=False must have at least one error")

    @classmethod
    def success(cls, value: Any, *, trace: Trace | None = None) -> "Result":
        return cls(ok=True, value=value, errors=(), trace=trace,
                   execution_id=trace.execution_id if trace else "")

    @classmethod
    def failure(cls, errors: "list[Error] | tuple[Error, ...]",
                *, trace: Trace | None = None) -> "Result":
        return cls(ok=False, value=None, errors=tuple(errors), trace=trace,
                   execution_id=trace.execution_id if trace else "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "value": self.value if self.ok else None,
            "errors": [e.to_dict() for e in self.errors],
            "trace": self.trace.to_dict() if self.trace else None,
            "execution_id": self.execution_id,
        }


@dataclass(frozen=True)
class VerificationReport:
    """Outcome of ``verify()``."""

    ok: bool
    verified_plan: "VerifiedPlan | None" = None
    errors: tuple[Error, ...] = ()

    def __post_init__(self) -> None:
        if self.ok and self.verified_plan is None:
            raise ValueError("ok=True must carry a VerifiedPlan")
        if not self.ok and self.verified_plan is not None:
            raise ValueError("ok=False must not carry a VerifiedPlan")
        if not self.ok and not self.errors:
            raise ValueError("ok=False must have at least one error")

    @classmethod
    def success(cls, verified_plan: "VerifiedPlan") -> "VerificationReport":
        return cls(ok=True, verified_plan=verified_plan, errors=())

    @classmethod
    def failure(cls, errors: "list[Error] | tuple[Error, ...]") -> "VerificationReport":
        return cls(ok=False, verified_plan=None, errors=tuple(errors))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "verified_plan": (
                self.verified_plan.serialize() if self.verified_plan else None
            ),
            "errors": [e.to_dict() for e in self.errors],
        }