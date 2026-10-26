"""
Structured execution metadata.

Produces safe, redacted ``Trace`` objects and (for application wiring)
hooks into audit systems. Never logs by default; *exposes* metadata for
the application to log. This keeps secrets, prompts, and raw argument
values out of Logix's own output.

The recorder deliberately stores no argument values, no handler return
values, and no model prompts — only step identifiers, capability names,
statuses, durations, and error codes. Redaction is the caller's job for
anything that *does* hold raw values (see ``_internal.redaction``).

See ``docs/system-design.md §8``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from logiq.results import StepTrace, Trace

__all__ = [
    "AuditHook",
    "ExecutionRecorder",
    "new_execution_id",
]


def new_execution_id() -> str:
    """Return a fresh execution identifier (128-bit hex)."""
    return uuid.uuid4().hex


@dataclass
class ExecutionRecorder:
    """
    Accumulates per-step metadata during one execution.

    Use ``record_step`` once per step, then ``finish`` to build the
    ``Trace``. The trace contains only safe fields — see ``StepTrace`` in
    ``logiq.results``. The ``steps`` list is public so an executor that
    wants to construct the trace itself (e.g. to attach it to a failure
    result before ``finish`` is called) can read it directly.
    """

    execution_id: str = field(default_factory=new_execution_id)
    plan_version: str = ""
    verification_duration_ms: float = 0.0
    steps: list[StepTrace] = field(default_factory=list)

    def record_step(
        self,
        *,
        step_id: str,
        capability: str,
        status: str,
        duration_ms: float,
        error_code: str | None = None,
    ) -> None:
        """Record one step. Appends a ``StepTrace`` to ``self.steps``."""
        self.steps.append(
            StepTrace(
                step_id=step_id,
                capability=capability,
                status=status,
                duration_ms=duration_ms,
                error_code=error_code,
            )
        )

    def finish(self) -> Trace:
        """Return a ``Trace`` built from the recorded steps."""
        return Trace(
            execution_id=self.execution_id,
            plan_version=self.plan_version,
            verification_duration_ms=self.verification_duration_ms,
            steps=tuple(self.steps),
        )


class AuditHook(Protocol):
    """
    Application-supplied audit hook.

    Attached via ``logiq.audit(hook)`` (reserved). Receives the same safe
    metadata that a ``Trace`` carries. Implementations must not raise —
    the pipeline swallows exceptions from audit hooks because a broken
    auditor must not block legitimate actions, but it also must not fail
    silently; log from within your hook.
    """

    def on_step(self, event: dict[str, Any]) -> None:
        """Called after every step, successful or not."""
        ...

    def on_result(self, event: dict[str, Any]) -> None:
        """Called once per execution with the final result summary."""
        ...
