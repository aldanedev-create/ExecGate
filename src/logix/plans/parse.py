"""
Plan parsing.

Turns an untrusted input (usually a dict from JSON, sometimes a JSON
string) into a normalized ``CanonicalPlan``. Structural problems are
reported as ``INVALID_PLAN`` errors.

This module does **not**:

- resolve capability names (that is the verifier),
- validate argument values against schemas (that is the verifier),
- run any handler.

It only enforces the plan's *shape*. That separation is what makes the
parser fast, deterministic, and safe to feed arbitrary AI output.

See ``docs/plan-format.md`` and ``docs/system-design.md §2``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping
from types import MappingProxyType

from logix.errors import Error, invalid_plan
from logix.plans.limits import DEFAULT_LIMITS, PlanLimits
from logix.plans.references import is_reference, parse_reference, Reference


SUPPORTED_PLAN_VERSIONS = frozenset({"1"})

_TOP_LEVEL_KEYS = frozenset({"version", "steps", "call", "with"})
_STEP_KEYS = frozenset({"id", "call", "with"})


@dataclass(frozen=True)
class CanonicalStep:
    """One normalized step. Still untrusted; schema validation happens later."""

    id: str
    capability: str
    arguments: Mapping[str, Any]
    """Argument map. Values may be literals or ``{$ref: ...}`` expressions."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))


@dataclass(frozen=True)
class CanonicalPlan:
    """A structurally valid plan. Not yet verified."""

    version: str
    steps: tuple[CanonicalStep, ...]
    single_call: bool
    """True when parsed from the concise ``{"call": ..., "with": ...}`` form."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_plan(
    plan: Any,
    *,
    limits: PlanLimits = DEFAULT_LIMITS,
) -> "CanonicalPlan | list[Error]":
    """
    Parse an untrusted plan into a ``CanonicalPlan`` or a list of errors.

    Accepts either form described in ``docs/plan-format.md``:

    Single call:
        {"call": "get_customer", "with": {"customer_id": 42}}

    Multi-step:
        {"version": "1",
         "steps": [
             {"id": "order", "call": "get_order", "with": {...}},
             {"id": "refund", "call": "issue_refund",
              "with": {"order_id": {"$ref": "order.id"}}},
         ]}
    """
    errors: list[Error] = []

    # 1. Accept a JSON string for convenience; the adapter path also uses this.
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError as e:
            return [invalid_plan(f"plan is not valid JSON: {e}")]

    # 2. Size limit, computed on the canonical serialization.
    if not isinstance(plan, (dict, list)):
        return [invalid_plan(f"plan must be a JSON object, got {type(plan).__name__}")]
    try:
        size = len(json.dumps(plan, separators=(",", ":"), default=str).encode("utf-8"))
        limits.check_bytes(size)
    except ValueError as e:
        return [invalid_plan(str(e))]

    if not isinstance(plan, dict):
        return [invalid_plan(f"plan must be a JSON object, got {type(plan).__name__}")]

    # 3. Depth limit, computed before structural parsing.
    try:
        limits.check_depth(_depth(plan))
    except ValueError as e:
        return [invalid_plan(str(e))]

    # 4. Reject unknown top-level fields.
    unknown_top = set(plan.keys()) - _TOP_LEVEL_KEYS
    if unknown_top:
        return [invalid_plan(f"unknown top-level fields: {sorted(unknown_top)}")]

    # 5. Dispatch to single or multi form.
    is_single = "call" in plan
    is_multi = "steps" in plan
    if is_single and is_multi:
        return [invalid_plan("plan cannot have both 'call' and 'steps'")]
    if not is_single and not is_multi:
        return [invalid_plan("plan must have either 'call' or 'steps'")]

    if is_single:
        return _parse_single(plan, limits)
    return _parse_multi(plan, limits)


# ---------------------------------------------------------------------------
# Single-call form
# ---------------------------------------------------------------------------

def _parse_single(plan: dict[str, Any], limits: PlanLimits) -> "CanonicalPlan | list[Error]":
    try:
        limits.check_steps(1)
    except ValueError as e:
        return [invalid_plan(str(e))]

    call = plan["call"]
    if not isinstance(call, str) or not call:
        return [invalid_plan("'call' must be a non-empty string", path="call")]

    args = plan.get("with", {})
    if not isinstance(args, dict):
        return [invalid_plan("'with' must be an object", path="with")]

    step_errors = _validate_refs_in_args(args, path="with", step_id=None)
    if step_errors:
        return step_errors

    step = CanonicalStep(id="", capability=call, arguments=args)
    return CanonicalPlan(
        version="1",
        steps=(step,),
        single_call=True,
    )


# ---------------------------------------------------------------------------
# Multi-step form
# ---------------------------------------------------------------------------

def _parse_multi(plan: dict[str, Any], limits: PlanLimits) -> "CanonicalPlan | list[Error]":
    errors: list[Error] = []

    version = plan.get("version", "1")
    if not isinstance(version, str) or version not in SUPPORTED_PLAN_VERSIONS:
        return [invalid_plan(
            f"unsupported plan version: {version!r}",
            path="version",
            supported=sorted(SUPPORTED_PLAN_VERSIONS),
        )]

    steps_raw = plan["steps"]
    if not isinstance(steps_raw, list):
        return [invalid_plan("'steps' must be a list", path="steps")]

    try:
        limits.check_steps(len(steps_raw))
    except ValueError as e:
        return [invalid_plan(str(e), path="steps")]

    steps: list[CanonicalStep] = []
    seen_ids: set[str] = set()

    for idx, step_raw in enumerate(steps_raw):
        step_err_prefix = f"steps[{idx}]"

        if not isinstance(step_raw, dict):
            errors.append(invalid_plan(
                f"step must be an object, got {type(step_raw).__name__}",
                path=step_err_prefix,
            ))
            continue

        unknown = set(step_raw.keys()) - _STEP_KEYS
        if unknown:
            errors.append(invalid_plan(
                f"unknown step fields: {sorted(unknown)}",
                path=step_err_prefix,
            ))
            continue

        step_id = step_raw.get("id")
        if not isinstance(step_id, str) or not step_id:
            errors.append(invalid_plan(
                "'id' must be a non-empty string",
                path=f"{step_err_prefix}.id",
            ))
            continue
        if step_id in seen_ids:
            errors.append(invalid_plan(
                f"duplicate step id: {step_id!r}",
                path=f"{step_err_prefix}.id",
            ))
            continue
        seen_ids.add(step_id)

        call = step_raw.get("call")
        if not isinstance(call, str) or not call:
            errors.append(invalid_plan(
                "'call' must be a non-empty string",
                path=f"{step_err_prefix}.call",
            ))
            continue

        args = step_raw.get("with", {})
        if not isinstance(args, dict):
            errors.append(invalid_plan(
                "'with' must be an object",
                path=f"{step_err_prefix}.with",
            ))
            continue

        ref_errors = _validate_refs_in_args(
            args, path=f"{step_err_prefix}.with", step_id=step_id
        )
        if ref_errors:
            errors.extend(ref_errors)
            continue

        steps.append(CanonicalStep(id=step_id, capability=call, arguments=args))

    if errors:
        return errors

    # Every $ref must point to an earlier step. The verifier re-checks this
    # with type information; here we only check ordering.
    earlier_ids = set()
    order_errors: list[Error] = []
    for step in steps:
        for ref_path, ref_value in _iter_refs(step.arguments):
            ref = parse_reference(ref_value)
            if isinstance(ref, Error):
                order_errors.append(ref)
                continue
            if ref.step_id not in earlier_ids:
                order_errors.append(invalid_plan(
                    f"$ref points to a non-earlier step: {ref.step_id!r}",
                    path=f"steps[{step.id}].with{ref_path}",
                    details={"step_id": ref.step_id, "ref": ref.as_string()},
                ))
        earlier_ids.add(step.id)

    if order_errors:
        return order_errors

    return CanonicalPlan(version=version, steps=tuple(steps), single_call=False)


# ---------------------------------------------------------------------------
# Reference validation within an argument map
# ---------------------------------------------------------------------------

def _validate_refs_in_args(
    args: Mapping[str, Any],
    *,
    path: str,
    step_id: str | None,
) -> list[Error]:
    """
    Validate any ``$ref`` values found inside ``args`` structurally.

    Forward-reference ordering is checked by the caller (it needs the set
    of earlier step ids). This function only validates the *grammar* of
    each ``$ref``.
    """
    errors: list[Error] = []
    for sub_path, value in _iter_refs(args):
        if step_id is None and path != "with":
            pass
        ref = parse_reference(value)
        if isinstance(ref, Error):
            ref = Error(
                code=ref.code,
                message=ref.message,
                path=f"{path}{sub_path}",
                details=ref.details,
            )
            errors.append(ref)
    return errors


def _iter_refs(value: Any, prefix: str = ""):
    """Yield (path_suffix, value) for every ``$ref`` value in a nested structure."""
    if is_reference(value):
        yield prefix, value
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            yield from _iter_refs(v, f"{prefix}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _iter_refs(v, f"{prefix}[{i}]")


def _depth(value: Any) -> int:
    """Return the maximum nesting depth of a JSON-compatible structure."""
    if isinstance(value, Mapping):
        return 1 + max((_depth(v) for v in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_depth(v) for v in value), default=0)
    return 1