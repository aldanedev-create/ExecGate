"""
The executor.

Accepts only a ``VerifiedPlan`` produced by the verifier on the same
engine. Runs steps in dependency order, running the recheck window before
each step, invoking the handler, validating output, and (for Pydantic)
normalizing output to JSON-safe values.

See ``docs/system-design.md §4`` and ADR-0004.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from logiq.capabilities import Capability, Registry
from logiq.context import ExecutionContext
from logiq.errors import (
    Error,
    execution_cancelled,
    handler_failed,
    output_validation_failed,
)
from logiq.ir import VerifiedPlan
from logiq.observability import ExecutionRecorder
from logiq.plans.references import (
    is_reference,
    parse_reference,
    resolve_reference,
)
from logiq.results import Result, Trace
from logiq.semantic import (
    RecheckStatus,
    recheck_step,
)
from logiq.semantic.invariants import InvariantRegistry

__all__ = ["execute_verified"]


def execute_verified(
    verified_plan: Any,
    *,
    registry: Registry,
    context: ExecutionContext | None = None,
    approval: Any = None,
    invariants: InvariantRegistry | None = None,
    idempotency_store: Any = None,
    audit_hook: Any = None,
) -> Result:
    """Execute a ``VerifiedPlan``."""
    if not isinstance(verified_plan, VerifiedPlan):
        raise TypeError(
            "execute() accepts only a VerifiedPlan produced by verify(); "
            f"got {type(verified_plan).__name__}"
        )

    recorder = ExecutionRecorder(plan_version=verified_plan.plan_version)
    start = time.monotonic()

    current_snapshot = registry.snapshot_hash()
    if current_snapshot != verified_plan.capability_snapshot_hash:
        err = Error(
            code="POLICY_REJECTED",
            message=(
                "capability registry changed between verify and execute; "
                "re-run verify() before executing this plan"
            ),
            path=None,
            details={
                "verified_hash": verified_plan.capability_snapshot_hash,
                "current_hash": current_snapshot,
            },
        )
        _fire_result(audit_hook, recorder.execution_id, verified_plan.plan_version, False, err.code)
        return Result.failure(
            [err],
            trace=Trace(
                execution_id=recorder.execution_id,
                plan_version=verified_plan.plan_version,
                verification_duration_ms=(time.monotonic() - start) * 1000,
                steps=(),
            ),
        )

    if invariants is None:
        invariants = InvariantRegistry()

    ctx = context if context is not None else ExecutionContext(principal="anonymous")

    step_outputs: dict[str, Any] = {}

    try:
        for step_id in verified_plan.dependency_order:
            step = next((s for s in verified_plan.steps if s.id == step_id), None)
            if step is None:
                raise RuntimeError(
                    f"executor: dependency_order references unknown step "
                    f"{step_id!r}; this is a verifier bug"
                )

            try:
                cap = registry.get(step.capability)
            except KeyError:
                raise RuntimeError(
                    f"executor: capability {step.capability!r} was "
                    f"unregistered after verify; this is a bug"
                ) from None

            step_start = time.monotonic()
            try:
                outcome = _execute_one_step(
                    step_id=step_id,
                    step=step,
                    cap=cap,
                    ctx=ctx,
                    approval=_resolve_approval(approval, step, step_id),
                    invariants=invariants,
                    idempotency_store=idempotency_store,
                    step_outputs=step_outputs,
                )
            except _StepFailure as failure:
                duration_ms = (time.monotonic() - step_start) * 1000
                recorder.record_step(
                    step_id=step_id,
                    capability=step.capability,
                    status="failed",
                    duration_ms=duration_ms,
                    error_code=failure.error.code,
                )
                _fire_step(
                    audit_hook,
                    recorder.execution_id,
                    step_id,
                    step.capability,
                    "failed",
                    duration_ms,
                    failure.error.code,
                )
                _fire_result(
                    audit_hook,
                    recorder.execution_id,
                    verified_plan.plan_version,
                    False,
                    failure.error.code,
                )
                trace = Trace(
                    execution_id=recorder.execution_id,
                    plan_version=verified_plan.plan_version,
                    verification_duration_ms=(time.monotonic() - start) * 1000,
                    steps=tuple(recorder.steps),
                )
                return Result.failure([failure.error], trace=trace)

            step_outputs[step_id] = outcome
            duration_ms = (time.monotonic() - step_start) * 1000
            recorder.record_step(
                step_id=step_id,
                capability=step.capability,
                status="ok",
                duration_ms=duration_ms,
            )
            _fire_step(
                audit_hook,
                recorder.execution_id,
                step_id,
                step.capability,
                "ok",
                duration_ms,
                None,
            )

    except Exception:
        _fire_result(
            audit_hook,
            recorder.execution_id,
            verified_plan.plan_version,
            False,
            "EXECUTION_CANCELLED",
        )
        return Result.failure(
            [execution_cancelled()],
            trace=Trace(
                execution_id=recorder.execution_id,
                plan_version=verified_plan.plan_version,
                verification_duration_ms=(time.monotonic() - start) * 1000,
                steps=tuple(recorder.steps),
            ),
        )

    trace = Trace(
        execution_id=recorder.execution_id,
        plan_version=verified_plan.plan_version,
        verification_duration_ms=(time.monotonic() - start) * 1000,
        steps=tuple(recorder.steps),
    )

    if verified_plan.single_call:
        only_step_id = verified_plan.steps[0].id
        value = step_outputs.get(only_step_id)
    else:
        value = dict(step_outputs)

    _fire_result(
        audit_hook,
        recorder.execution_id,
        verified_plan.plan_version,
        True,
        None,
    )
    return Result.success(value, trace=trace)


# ---------------------------------------------------------------------------
# One step
# ---------------------------------------------------------------------------


class _StepFailure(Exception):  # noqa: N818
    def __init__(self, error: Error) -> None:
        super().__init__(error.message)
        self.error = error


def _execute_one_step(
    *,
    step_id: str,
    step: Any,
    cap: Capability,
    ctx: ExecutionContext,
    approval: Any,
    invariants: InvariantRegistry,
    idempotency_store: Any,
    step_outputs: dict[str, Any],
) -> Any:
    # 1. Resolve references.
    resolved_args: dict[str, Any] = {}
    for arg_name, arg_value in step.arguments.items():
        if is_reference(arg_value):
            parsed = parse_reference(arg_value)
            if isinstance(parsed, Error):
                raise _StepFailure(
                    Error(
                        code=parsed.code,
                        message=parsed.message,
                        path=f"{step_id}.{arg_name}",
                        details=parsed.details,
                    )
                )
            resolved = resolve_reference(parsed, step_outputs)
            if isinstance(resolved, Error):
                raise _StepFailure(
                    Error(
                        code=resolved.code,
                        message=resolved.message,
                        path=f"{step_id}.{arg_name}",
                        details=resolved.details,
                    )
                )
            resolved_args[arg_name] = resolved
        else:
            resolved_args[arg_name] = arg_value

    # 2. Compute idempotency key if the capability is idempotent.
    if cap.idempotent:
        from logiq.approval import canonical_args_hash

        idem_hash = canonical_args_hash(resolved_args)
        idem_key: str | None = f"{cap.name}:{idem_hash}"
    else:
        idem_key = None
        idem_hash = None

    # 3. Recheck window: invariants, approval, idempotency.
    recheck = recheck_step(
        capability=step.capability,
        args=resolved_args,
        context=ctx,
        invariants=invariants,
        approval_token=approval,
        approval_required_flag=cap.requires_approval,
        idempotency_store=idempotency_store,
        idempotency_key=idem_key,
        idempotency_args_hash=idem_hash,
        context_refresher=None,
    )

    if recheck.status is RecheckStatus.REPLAY:
        return recheck.cached_value
    if recheck.status is RecheckStatus.APPROVAL_REQUIRED:
        raise _StepFailure(
            recheck.error
            or Error(
                code="APPROVAL_REQUIRED",
                message="approval required",
                path=step_id,
            )
        )
    if recheck.status is RecheckStatus.DENY:
        raise _StepFailure(
            recheck.error
            or Error(
                code="POLICY_REJECTED",
                message="step rejected",
                path=step_id,
            )
        )

    # 4. Prepare arguments for the handler (Pydantic model conversion).
    handler_args = _prepare_handler_args(cap, resolved_args)

    # 5. Invoke the handler.
    try:
        output = cap.handler(**handler_args)
    except Exception as e:
        if cap.idempotent and idempotency_store is not None and idem_key is not None:
            idempotency_store.release(idem_key)
        raise _StepFailure(
            handler_failed(
                cap.name,
                f"{type(e).__name__}: {e}",
                path=step_id,
            )
        ) from e

    # 6. Validate and normalize output.
    try:
        if cap.output_schema is not None:
            schema_errors = cap.output_schema.validate(output, path=step_id)
            if schema_errors:
                raise _StepFailure(
                    output_validation_failed(
                        f"handler return value does not match declared output schema: "
                        f"{schema_errors[0].message}",
                        path=step_id,
                        details={"first_error": schema_errors[0].message},
                    )
                )
        if cap.output_schema is not None and hasattr(cap.output_schema, "prepare_output"):
            output = cap.output_schema.prepare_output(output)
    except _StepFailure:
        if cap.idempotent and idempotency_store is not None and idem_key is not None:
            idempotency_store.release(idem_key)
        raise
    except Exception as e:
        if cap.idempotent and idempotency_store is not None and idem_key is not None:
            idempotency_store.release(idem_key)
        raise _StepFailure(
            output_validation_failed(
                f"output normalization failed: {type(e).__name__}: {e}",
                path=step_id,
            )
        ) from e

    # 7. Commit idempotency on success.
    if cap.idempotent and idempotency_store is not None and idem_key is not None:
        idempotency_store.commit(idem_key, output)

    return output


# ---------------------------------------------------------------------------
# Approval resolution
# ---------------------------------------------------------------------------


def _resolve_approval(approval: Any, step: Any, step_id: str) -> Any:
    if approval is None:
        return None
    if isinstance(approval, dict):
        if step.capability in approval:
            return approval[step.capability]
        if step_id in approval:
            return approval[step_id]
        return None
    return approval


# ---------------------------------------------------------------------------
# Pydantic handler preparation
# ---------------------------------------------------------------------------


def _prepare_handler_args(cap: Capability, resolved_args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    mode = "model"
    for arg_name, arg_value in resolved_args.items():
        field_type = cap.input_schema.fields.get(arg_name)
        if field_type is not None and hasattr(field_type, "prepare_input"):
            try:
                from logiq_pydantic import get_handler_mode

                mode = get_handler_mode().value
            except ImportError:
                pass
            out[arg_name] = field_type.prepare_input(arg_value, mode)
        else:
            out[arg_name] = arg_value
    return out


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------


def _fire_step(
    hook: Any,
    execution_id: str,
    step_id: str,
    capability: str,
    status: str,
    duration_ms: float,
    error_code: str | None,
) -> None:
    if hook is None:
        return
    with contextlib.suppress(Exception):
        hook.on_step(
            {
                "execution_id": execution_id,
                "step_id": step_id,
                "capability": capability,
                "status": status,
                "duration_ms": duration_ms,
                "error_code": error_code,
            }
        )


def _fire_result(
    hook: Any,
    execution_id: str,
    plan_version: str,
    ok: bool,
    error_code: str | None,
) -> None:
    if hook is None:
        return
    with contextlib.suppress(Exception):
        hook.on_result(
            {
                "execution_id": execution_id,
                "plan_version": plan_version,
                "ok": ok,
                "error_code": error_code,
            }
        )
