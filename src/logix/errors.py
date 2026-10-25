"""
The stable error taxonomy.

Error codes are part of the public contract: adding a code is a minor
change, renaming or removing one is a major change. Clients and the repair
loop switch on ``code``; the message is for humans and must be safe
(redacted — see ``_internal/redaction.py``).

See ``docs/api-reference.md §14`` and ``docs/system-design.md §7``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Stable codes. Do not rename. Add only with a changelog entry.
# ---------------------------------------------------------------------------

INVALID_PLAN = "INVALID_PLAN"
UNKNOWN_CAPABILITY = "UNKNOWN_CAPABILITY"
SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
INVALID_REFERENCE = "INVALID_REFERENCE"
DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
POLICY_REJECTED = "POLICY_REJECTED"
AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
HANDLER_FAILED = "HANDLER_FAILED"
OUTPUT_VALIDATION_FAILED = "OUTPUT_VALIDATION_FAILED"
EXECUTION_CANCELLED = "EXECUTION_CANCELLED"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
GROUNDING_REQUIRED = "GROUNDING_REQUIRED"
ADAPTER_ERROR = "ADAPTER_ERROR"

ALL_CODES: frozenset[str] = frozenset({
    INVALID_PLAN,
    UNKNOWN_CAPABILITY,
    SCHEMA_VALIDATION_FAILED,
    INVALID_REFERENCE,
    DEPENDENCY_CYCLE,
    POLICY_REJECTED,
    AUTHORIZATION_FAILED,
    APPROVAL_REQUIRED,
    RESOURCE_LIMIT_EXCEEDED,
    HANDLER_FAILED,
    OUTPUT_VALIDATION_FAILED,
    EXECUTION_CANCELLED,
    IDEMPOTENCY_CONFLICT,
    GROUNDING_REQUIRED,
    ADAPTER_ERROR,
})


# ---------------------------------------------------------------------------
# Error — the object that crosses the boundary
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Error:
    """
    A structured failure.

    ``code`` is one of the stable codes above. ``path`` points into the
    plan (e.g. ``"arguments.customer_id"``, ``"steps[2].with.amount"``)
    when applicable. ``message`` is human-readable and redacted. ``details``
    is for machine use and must not contain secrets.
    """

    code: str
    message: str
    path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.code not in ALL_CODES:
            raise ValueError(f"unknown error code: {self.code!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "details": dict(self.details),
        }


# ---------------------------------------------------------------------------
# Convenience constructors used by the pipeline stages
# ---------------------------------------------------------------------------

def invalid_plan(message: str, *, path: str | None = None, **details: Any) -> Error:
    return Error(INVALID_PLAN, message, path, details)


def unknown_capability(name: str, *, path: str | None = None) -> Error:
    return Error(UNKNOWN_CAPABILITY, f"unknown capability: {name!r}", path)


def schema_validation_failed(message: str, *, path: str | None = None, **details: Any) -> Error:
    return Error(SCHEMA_VALIDATION_FAILED, message, path, details)


def invalid_reference(message: str, *, path: str | None = None, **details: Any) -> Error:
    return Error(INVALID_REFERENCE, message, path, details)


def dependency_cycle(message: str, *, path: str | None = None, **details: Any) -> Error:
    return Error(DEPENDENCY_CYCLE, message, path, details)


def policy_rejected(message: str, *, path: str | None = None, **details: Any) -> Error:
    return Error(POLICY_REJECTED, message, path, details)


def authorization_failed(message: str, *, path: str | None = None, **details: Any) -> Error:
    return Error(AUTHORIZATION_FAILED, message, path, details)


def approval_required(capability: str, *, path: str | None = None) -> Error:
    return Error(APPROVAL_REQUIRED, f"approval required for {capability!r}", path)


def resource_limit_exceeded(message: str, *, path: str | None = None, **details: Any) -> Error:
    return Error(RESOURCE_LIMIT_EXCEEDED, message, path, details)


def handler_failed(capability: str, message: str, *, path: str | None = None) -> Error:
    # Never include the raw exception text unless it has been redacted.
    return Error(HANDLER_FAILED, f"{capability}: {message}", path)


def output_validation_failed(message: str, *, path: str | None = None, **details: Any) -> Error:
    return Error(OUTPUT_VALIDATION_FAILED, message, path, details)


def execution_cancelled(*, path: str | None = None) -> Error:
    return Error(EXECUTION_CANCELLED, "execution cancelled", path)


def idempotency_conflict(key: str, *, path: str | None = None) -> Error:
    return Error(IDEMPOTENCY_CONFLICT, f"idempotency conflict for key {key!r}", path)


def grounding_required(message: str, *, path: str | None = None, **details: Any) -> Error:
    return Error(GROUNDING_REQUIRED, message, path, details)


def adapter_error(message: str, *, provider: str | None = None) -> Error:
    # Adapters never reach the trust side; the application translates this
    # to INVALID_PLAN before entering Logix.
    details = {"provider": provider} if provider else {}
    return Error(ADAPTER_ERROR, message, None, details)