"""
The verifier.

Runs the static checks and produces a ``VerifiedPlan`` (or a list of
``Error``). Static checks are those that cannot be invalidated by live
external state:

1. capability resolution (unknown capability)
2. argument schema validation
3. reference resolution and structural type compatibility
4. dependency graph (no cycles; topological order computed)
5. resource limits (delegated to ``plans.parse``; enforced there)
6. statically checkable policies (deferred — dynamic checks live in recheck)

The verifier does *not* run authorization checks, approvals, idempotency,
or any check that reads live state. Those run in the recheck window
(``semantic.recheck``). See ``docs/system-design.md §2`` and ADR-0004.

Verification is **not** an authorization grant. A ``VerifiedPlan`` is
proof that the plan was structurally valid and statically permitted at
verify time; ``execute()`` re-earns the dynamic guarantees.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from logiq._internal import canonical_hash
from logiq.capabilities import Capability, Registry
from logiq.context import ExecutionContext
from logiq.errors import (
    Error,
    invalid_reference,
    schema_validation_failed,
    unknown_capability,
)
from logiq.ir import VerifiedStep, _construct_verified_plan
from logiq.plans import CanonicalPlan, CanonicalStep
from logiq.plans.references import is_reference, parse_reference
from logiq.schemas import (
    AnyType,
    BoolType,
    DictType,
    FloatType,
    IntType,
    ListType,
    LiteralType,
    NoneType,
    ObjectType,
    StrType,
    Type,
    UnionType,
)
from logiq.schemas.validate import ConstrainedType

if TYPE_CHECKING:
    pass


__all__ = ["verify_plan"]


def verify_plan(
    plan: Any,
    *,
    registry: Registry,
    limits: Any,
    context: ExecutionContext | None = None,
    policies: Any = None,
) -> tuple[Any | None, list[Error]]:
    """
    Run all static checks.

    Parameters
    ----------
    plan
        A ``CanonicalPlan`` from ``plans.parse_plan``. (The engine always
        passes a CanonicalPlan; a raw dict here is a caller bug.)
    registry
        The capability registry to resolve against.
    limits
        ``PlanLimits`` for resource bounds. Already enforced at parse
        time; accepted here for the executor's invocation-count check.
    context
        Optional ``ExecutionContext`` for statically checkable policies.
    policies
        Optional ``PolicySet`` for static policy hooks. In 0.1.0 all
        policies run dynamically in the recheck window, so this is
        currently unused but accepted for API stability.

    Returns
    -------
    ``(VerifiedPlan, [])`` on success, or ``(None, errors)`` on failure.
    Never invokes a handler.
    """
    if not isinstance(plan, CanonicalPlan):
        # Caller error — the engine always hands us a CanonicalPlan.
        from logiq.errors import invalid_plan

        return None, [invalid_plan(f"verifier requires a CanonicalPlan; got {type(plan).__name__}")]

    errors: list[Error] = []

    # ------------------------------------------------------------------
    # Pass 1 — resolve every step's capability. Build a step id -> step
    # map and a capability map, both used by later passes.
    # ------------------------------------------------------------------
    steps_by_id: dict[str, tuple[CanonicalStep, Capability, int]] = {}
    for idx, step in enumerate(plan.steps):
        # The parser guarantees step.id is unique within a multi-step plan
        # and is "" for single-call plans. Assign the synthetic id "0" for
        # single-call steps so downstream code has a uniform key.
        step_id = step.id if step.id else "__single__"
        try:
            cap = registry.get(step.capability)
        except KeyError:
            errors.append(
                unknown_capability(
                    step.capability,
                    path=_step_path(plan, idx),
                )
            )
            continue
        steps_by_id[step_id] = (step, cap, idx)

    if errors:
        return None, errors

    # ------------------------------------------------------------------
    # Pass 2 — for each step, validate arguments (literal or reference).
    # References resolve against *earlier* steps' declared output schemas.
    # ------------------------------------------------------------------
    resolved_output_types: dict[str, Type] = {}
    for idx, step in enumerate(plan.steps):
        step_id = step.id if step.id else "__single__"
        step_entry = steps_by_id.get(step_id)
        if step_entry is None:
            continue  # capability resolution already failed for this step
        _, cap, _ = step_entry

        arg_errors = _validate_arguments(
            plan=plan,
            step=step,
            step_id=step_id,
            capability=cap,
            registry=registry,
            earlier_output_types=resolved_output_types,
            step_index=idx,
        )
        errors.extend(arg_errors)

        # Record this step's output type for later steps to reference.
        # If output_schema is None, downstream references are unresolvable
        # and will error at that point, which is the correct behavior.
        if cap.output_schema is not None:
            resolved_output_types[step_id] = cap.output_schema
        # If output_schema is None, omit from the map; downstream $ref to
        # this step will error with a clear message.

    if errors:
        return None, errors

    # ------------------------------------------------------------------
    # Pass 3 — dependency graph. Every $ref implies an edge. Detect
    # cycles, compute a topological order.
    # ------------------------------------------------------------------
    order, cycle_errors = _dependency_order(plan)
    if cycle_errors:
        return None, cycle_errors

    # ------------------------------------------------------------------
    # Pass 4 — build the VerifiedPlan.
    # ------------------------------------------------------------------
    verified_steps = tuple(
        VerifiedStep(
            id=step.id if step.id else "__single__",
            capability=step.capability,
            arguments=dict(step.arguments),
        )
        for step in plan.steps
    )

    snapshot_hash = registry.snapshot_hash()

    # The verification hash binds together everything static about the
    # plan, so a VerifiedPlan cannot be modified (or reconstructed
    # differently) without detection.
    verification_payload = {
        "plan_version": plan.version,
        "steps": [
            {
                "id": s.id,
                "call": s.capability,
                "with": dict(s.arguments),
            }
            for s in verified_steps
        ],
        "dependency_order": list(order),
        "capability_snapshot_hash": snapshot_hash,
    }
    verification_hash = canonical_hash(verification_payload)

    verified = _construct_verified_plan(
        plan_version=plan.version,
        steps=verified_steps,
        dependency_order=tuple(order),
        capability_snapshot_hash=snapshot_hash,
        verification_hash=verification_hash,
        single_call=plan.single_call,
    )
    return verified, []


# ---------------------------------------------------------------------------
# Argument validation (schema + references)
# ---------------------------------------------------------------------------


def _validate_arguments(
    *,
    plan: CanonicalPlan,
    step: CanonicalStep,
    step_id: str,
    capability: Capability,
    registry: Registry,
    earlier_output_types: dict[str, Type],
    step_index: int,
) -> list[Error]:
    """Validate one step's argument map."""
    errors: list[Error] = []
    schema = capability.input_schema
    path_prefix = _step_path(plan, step_index)

    # Required fields present.
    for required_name in schema.required:
        if required_name not in step.arguments:
            errors.append(
                schema_validation_failed(
                    f"missing required field {required_name!r}",
                    path=f"{path_prefix}.{required_name}",
                )
            )

    # Unknown fields rejected (ObjectType.additional is False by default,
    # but we check here explicitly so the error names the step).
    unknown = set(step.arguments.keys()) - set(schema.fields.keys())
    for name in sorted(unknown):
        errors.append(
            schema_validation_failed(
                f"unknown argument {name!r}",
                path=f"{path_prefix}.{name}",
            )
        )

    # Each present argument: validate literal or check reference type.
    for arg_name, arg_value in step.arguments.items():
        if arg_name not in schema.fields:
            continue  # already reported as unknown
        dest_type = schema.fields[arg_name]
        arg_path = f"{path_prefix}.{arg_name}"

        if is_reference(arg_value):
            err = _check_reference(
                ref_value=arg_value,
                dest_type=dest_type,
                earlier_output_types=earlier_output_types,
                path=arg_path,
            )
            if err is not None:
                errors.append(err)
            continue

        # Literal value: validate against the schema now. The executor
        # re-validates at run time (the schema might accept the same value
        # here and there — this is a "fail fast" static check).
        for schema_err in dest_type.validate(arg_value, arg_path):
            errors.append(
                schema_validation_failed(
                    schema_err.message,
                    path=schema_err.path,
                )
            )

    return errors


def _check_reference(
    *,
    ref_value: dict[str, Any],
    dest_type: Type,
    earlier_output_types: dict[str, Type],
    path: str,
) -> Error | None:
    """Resolve a ``$ref`` and check type compatibility against ``dest_type``."""
    parsed = parse_reference(ref_value)
    if isinstance(parsed, Error):
        # Re-wrap with the correct argument path.
        return Error(
            code=parsed.code,
            message=parsed.message,
            path=path,
            details=parsed.details,
        )

    # The referenced step must have a declared output schema (otherwise
    # its output is untyped and cannot be safely referenced).
    src_root = earlier_output_types.get(parsed.step_id)
    if src_root is None:
        return invalid_reference(
            f"cannot reference {parsed.step_id!r}: "
            f"either it does not exist or its capability has no declared "
            f"output schema",
            path=path,
            details={"step_id": parsed.step_id},
        )

    # Walk the path through the source output type.
    src_leaf = _walk_type_path(src_root, parsed.path)
    if src_leaf is None:
        return invalid_reference(
            f"path {parsed.as_string()!r} does not exist in the "
            f"referenced capability's declared output schema",
            path=path,
            details={"ref": parsed.as_string()},
        )

    # Structural compatibility check.
    if not _assignable(src_leaf, dest_type):
        return invalid_reference(
            f"reference type {_type_name(src_leaf)} is not assignable to "
            f"destination type {_type_name(dest_type)}",
            path=path,
            details={
                "ref": parsed.as_string(),
                "src": _type_name(src_leaf),
                "dst": _type_name(dest_type),
            },
        )

    return None


def _walk_type_path(root: Type, path: tuple[str, ...]) -> Type | None:
    """
    Navigate a ``Type`` by a reference path, using each type's ``walk``
    method. Returns the leaf ``Type``, or None if the path does not
    structurally exist.
    """
    current: Type = root
    for segment in path:
        walk = getattr(current, "walk", None)
        if walk is None:
            return None
        nxt = walk(segment)
        if nxt is None:
            return None
        current = nxt
    return current


def _assignable(src: Type, dst: Type) -> bool:
    """
    Pragmatic structural assignability.

    Accepts ``src`` if a value of type ``src`` can be safely passed where
    ``dst`` is expected. This is conservative: it does not implement full
    subtyping (no ``int`` -> ``float`` widening, no ``Literal["a"]`` ->
    ``str`` coercion — those are coerced at the executor's option, not
    here). It answers:

    - primitive == primitive (same class)
    - ObjectType(src) is assignable to ObjectType(dst) if all required
      dst fields exist in src with assignable types
    - ListType(src) is assignable to ListType(dst) if item types are
      assignable
    - UnionType(src) is assignable to dst if *any* member is assignable
      to dst (a value could be any of them)
    - UnionType(dst) accepts src if *any* dst member accepts it
    - ConstrainedType unwraps to its base for the comparison

    Documented limitation: no cross-type coercion. If a plan needs
    ``int``-to-``float``, the caller should declare ``float`` and pass a
    float, or use ``NumberType`` explicitly.
    """
    while isinstance(src, ConstrainedType):
        src = src.base
    while isinstance(dst, ConstrainedType):
        dst = dst.base

    if isinstance(src, AnyType):
        return True
    if isinstance(src, UnionType):
        return any(_assignable(m, dst) for m in src.members)
    if isinstance(dst, UnionType):
        return any(_assignable(src, m) for m in dst.members)
    if isinstance(dst, AnyType):
        return True

    if type(src) is type(dst):
        if isinstance(src, ObjectType):
            assert isinstance(dst, ObjectType)
            for req in dst.required:
                if req not in src.fields:
                    return False
                if not _assignable(src.fields[req], dst.fields[req]):
                    return False
            return True
        if isinstance(src, ListType):
            assert isinstance(dst, ListType)
            return _assignable(src.item_type, dst.item_type)
        if isinstance(src, DictType):
            assert isinstance(dst, DictType)
            return _assignable(src.value_type, dst.value_type)
        return True  # primitive or literal or None: same class is enough

    return False


def _type_name(t: Type) -> str:
    """Human-readable name of a Type, for error messages."""
    if isinstance(t, IntType):
        return "int"
    if isinstance(t, FloatType):
        return "float"
    if isinstance(t, StrType):
        return "str"
    if isinstance(t, BoolType):
        return "bool"
    if isinstance(t, NoneType):
        return "None"
    if isinstance(t, AnyType):
        return "Any"
    if isinstance(t, ListType):
        return f"list[{_type_name(t.item_type)}]"
    if isinstance(t, DictType):
        return f"dict[str, {_type_name(t.value_type)}]"
    if isinstance(t, ObjectType):
        return "object"
    if isinstance(t, LiteralType):
        return f"Literal[{', '.join(map(repr, t.values))}]"
    if isinstance(t, UnionType):
        return " | ".join(_type_name(m) for m in t.members)
    if isinstance(t, ConstrainedType):
        return _type_name(t.base)
    # PydanticType or an adapter-defined type
    return type(t).__name__


# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------


def _dependency_order(
    plan: CanonicalPlan,
) -> tuple[list[str], list[Error]]:
    """
    Compute a topological order over step ids.

    Edges are implied by ``$ref`` expressions: step B depends on step A
    if B's arguments contain ``{$ref: "A...."}``. The parser already
    guarantees forward references are rejected (``$ref`` to a later step
    fails at parse time), so this pass is mostly belt-and-suspenders and
    produces the ordered list the executor walks.

    Cycles cannot occur if the parser is correct (back-edges are
    forward-refs from the earlier step's perspective — but wait, a
    later step referencing an earlier step is fine; a cycle would require
    step A to reference step B *and* B to reference A, which means A is
    earlier and B is later, so B→A is fine and A→B is a forward ref,
    which the parser rejects). So cycles are impossible given the parser
    guarantees. If we detect one anyway, it's a bug worth reporting.
    """
    # For single-call plans there are no references and no cycles.
    if plan.single_call:
        step = plan.steps[0]
        return [step.id if step.id else "__single__"], []

    edges: dict[str, set[str]] = {s.id: set() for s in plan.steps}
    step_order: dict[str, int] = {s.id: i for i, s in enumerate(plan.steps)}

    for step in plan.steps:
        for _, value in _iter_refs(step.arguments):
            ref = parse_reference(value)
            if isinstance(ref, Error):
                continue  # already reported in pass 2
            if ref.step_id in edges:
                edges[step.id].add(ref.step_id)

    # Kahn's algorithm.
    in_degree = {sid: 0 for sid in edges}
    for sid, deps in edges.items():
        in_degree[sid] = len(deps)
    ready = [sid for sid, deg in in_degree.items() if deg == 0]
    # Stable tie-breaking by original step order.
    ready.sort(key=lambda sid: step_order[sid])

    order: list[str] = []
    while ready:
        sid = ready.pop(0)
        order.append(sid)
        for other, deps in edges.items():
            if sid in deps:
                deps.discard(sid)
                in_degree[other] = len(deps)
                if in_degree[other] == 0 and other not in order and other not in ready:
                    ready.append(other)
        ready.sort(key=lambda s: step_order[s])

    if len(order) != len(edges):
        # A cycle. This should be unreachable given the parser's guarantee,
        # but report it clearly if it happens.
        from logiq.errors import dependency_cycle

        cyclic = sorted(set(edges) - set(order))
        return [], [
            dependency_cycle(
                f"cycle detected among steps: {cyclic}",
            )
        ]

    return order, []


def _iter_refs(args: Mapping[str, Any], prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Yield (path, value) for every $ref in a nested argument map."""
    for k, v in args.items():
        child_prefix = f"{prefix}.{k}" if prefix else k
        if is_reference(v):
            yield child_prefix, v
        elif isinstance(v, dict):
            yield from _iter_refs(v, child_prefix)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                yield from _iter_refs({str(i): item}, child_prefix)


def _step_path(plan: CanonicalPlan, index: int) -> str:
    return "with" if plan.single_call else f"steps[{index}].with"
