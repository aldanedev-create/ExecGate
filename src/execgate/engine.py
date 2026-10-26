"""
The Logix engine.

See ``docs/usage-model.md`` and ``docs/system-design.md``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from execgate.capabilities import Registry, build_capability
from execgate.context import ExecutionContext
from execgate.plans import DEFAULT_LIMITS, PlanLimits, parse_plan
from execgate.policies import PolicySet
from execgate.results import Result, VerificationReport
from execgate.semantic import (
    GroundingPolicy,
    InMemoryIdempotencyStore,
    InvariantRegistry,
    check_grounding,
)
from execgate.tools import ToolCatalog

if TYPE_CHECKING:
    from execgate.capabilities import Capability
    from execgate.ir import VerifiedPlan


__all__ = ["Logix"]


class Logix:
    """An isolated Logix runtime."""

    def __init__(
        self,
        *,
        limits: PlanLimits | None = None,
        idempotency_store: Any = None,
    ) -> None:
        self._registry = Registry()
        self._limits = limits if limits is not None else DEFAULT_LIMITS
        self._policies = PolicySet()
        self._invariants = InvariantRegistry()
        self._grounding = GroundingPolicy()
        self._idempotency_store = (
            idempotency_store if idempotency_store is not None else InMemoryIdempotencyStore()
        )
        self._tools = ToolCatalog(self._registry)
        self._capability = _CapabilityRegistrar(self)
        self._audit_hook: Any = None  # ADDED

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    @property
    def capability(self) -> _CapabilityRegistrar:
        """Capability registration surface. See ``docs/api-reference.md §3``."""
        return self._capability

    # ------------------------------------------------------------------
    # Policy configuration
    # ------------------------------------------------------------------

    def authorize(
        self,
        capability: str | Callable[..., Any],
        *,
        check: Callable[[dict[str, Any], ExecutionContext], Any],
    ) -> None:
        name = _as_capability_name(capability)
        self._invariants.add(name, check)

    def require_approval(
        self,
        capability: str | Callable[..., Any],
        *,
        principal_bound: bool = True,
    ) -> None:
        name = _as_capability_name(capability)
        cap = self._registry.get(name)
        if cap.requires_approval:
            return
        new_cap = dataclasses.replace(cap, requires_approval=True)
        self._registry.unregister(name)
        self._registry.add(new_cap)

    def policy(self, name: str, *, rule: Callable[..., Any]) -> None:
        self._policies.add(name, rule)

    def grounding(
        self,
        *,
        require_ref_for: Iterable[str] = (),
        literal_allowlist: Iterable[str] = (),
    ) -> None:
        self._grounding = GroundingPolicy(
            require_ref=frozenset(require_ref_for),
            literal_allowlist=frozenset(literal_allowlist),
        )

    def limits(
        self,
        *,
        max_steps: int | None = None,
        max_bytes: int | None = None,
        max_depth: int | None = None,
        max_invocations: int | None = None,
    ) -> None:
        overrides: dict[str, int] = {}
        if max_steps is not None:
            overrides["max_steps"] = max_steps
        if max_bytes is not None:
            overrides["max_bytes"] = max_bytes
        if max_depth is not None:
            overrides["max_depth"] = max_depth
        if max_invocations is not None:
            overrides["max_invocations"] = max_invocations
        if overrides:
            self._limits = dataclasses.replace(self._limits, **overrides)

    def context(self, **kwargs: Any) -> ExecutionContext:
        return ExecutionContext(**kwargs)

    def audit(self, hook: Any) -> None:  # ADDED
        """
        Attach an audit hook (see ``execgate.observability.AuditHook``).

        Hook ``on_step(event)`` runs after each step; ``on_result(event)``
        runs once per execution. Exceptions from the hook are swallowed —
        a broken auditor must not block legitimate actions — but you
        should not rely on that; log from within the hook.
        """
        self._audit_hook = hook

    # ------------------------------------------------------------------
    # Execution entry points
    # ------------------------------------------------------------------

    def verify(
        self,
        plan: Any,
        *,
        context: ExecutionContext | None = None,
    ) -> VerificationReport:
        parsed = parse_plan(plan, limits=self._limits)
        if isinstance(parsed, list):
            return VerificationReport.failure(parsed)

        grounding_errors = check_grounding(parsed, self._grounding)
        if grounding_errors:
            return VerificationReport.failure(grounding_errors)

        from execgate.verifier import verify_plan

        verified, errors = verify_plan(
            parsed,
            registry=self._registry,
            limits=self._limits,
            context=context,
            policies=self._policies,
        )
        if errors:
            return VerificationReport.failure(errors)
        if verified is None:
            raise RuntimeError(
                "execgate.verifier.verify_plan returned neither a VerifiedPlan "
                "nor errors; this is a bug in the verifier"
            )
        return VerificationReport.success(verified)

    def execute(
        self,
        verified_plan: VerifiedPlan,
        *,
        context: ExecutionContext | None = None,
        approval: Any = None,
    ) -> Result:
        from execgate.executor import execute_verified

        return execute_verified(
            verified_plan,
            registry=self._registry,
            context=context,
            approval=approval,
            invariants=self._invariants,
            idempotency_store=self._idempotency_store,
            audit_hook=self._audit_hook,  # ADDED
            # policies= removed — not in execute_verified signature
        )

    def run(
        self,
        plan: Any,
        *,
        context: ExecutionContext | None = None,
    ) -> Result:
        report = self.verify(plan, context=context)
        if not report.ok:
            return Result.failure(report.errors)
        # report.ok guarantees verified_plan is not None
        return self.execute(report.verified_plan, context=context)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Reserved APIs
    # ------------------------------------------------------------------

    def dry_run(
        self,
        plan: Any,
        *,
        context: ExecutionContext | None = None,
    ) -> Any:
        raise NotImplementedError("Logix.dry_run — reserved for 0.1.0")

    def explain(self, plan: Any) -> str:
        raise NotImplementedError("Logix.explain — reserved for 0.1.0")

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def registry(self) -> Registry:
        return self._registry

    @property
    def schemas(self) -> _SchemaCatalog:
        return _SchemaCatalog(self._registry)

    @property
    def tools(self) -> ToolCatalog:
        return self._tools


# ---------------------------------------------------------------------------
# Capability registrar
# ---------------------------------------------------------------------------


class _CapabilityRegistrar:
    """The object behind ``execgate.capability``."""

    __slots__ = ("_engine",)

    def __init__(self, engine: Logix) -> None:
        self._engine = engine

    def __call__(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        effects: str | None = None,
        requires_approval: bool = False,
        idempotent: bool = False,  # ADDED
    ) -> Any:
        def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
            cap = build_capability(
                f,
                name=name,
                description=description,
                effects=effects,
                requires_approval=requires_approval,
                idempotent=idempotent,  # ADDED
            )
            self._engine._registry.add(cap)
            return f

        if fn is not None:
            return decorator(fn)
        return decorator

    def register(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        effects: str | None = None,
        requires_approval: bool = False,
        idempotent: bool = False,  # ADDED
    ) -> Callable[..., Any]:
        cap = build_capability(
            fn,
            name=name,
            description=description,
            effects=effects,
            requires_approval=requires_approval,
            idempotent=idempotent,  # ADDED
        )
        self._engine._registry.add(cap)
        return fn

    def unregister(self, name: str) -> None:
        self._engine._registry.unregister(name)

    def get(self, name: str) -> Capability:
        return self._engine._registry.get(name)

    def names(self) -> list[str]:
        return self._engine._registry.names()

    def __iter__(self) -> Any:
        return iter(self._engine._registry)


# ---------------------------------------------------------------------------
# Schema catalog view
# ---------------------------------------------------------------------------


class _SchemaCatalog:
    __slots__ = ("_registry",)

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def for_capability(self, name: str) -> _CapabilitySchema:
        cap = self._registry.get(name)
        return _CapabilitySchema(
            name=cap.name,
            description=cap.description,
            input=cap.input_schema.to_json_schema(),
            output=(cap.output_schema.to_json_schema() if cap.output_schema is not None else None),
            input_type=cap.input_schema,
            output_type=cap.output_schema,
        )

    def names(self) -> list[str]:
        return self._registry.names()


@dataclasses.dataclass(frozen=True)
class _CapabilitySchema:
    name: str
    description: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    input_type: Any
    output_type: Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_capability_name(capability: str | Callable[..., Any]) -> str:
    if isinstance(capability, str):
        return capability
    name = getattr(capability, "__name__", None)
    if not isinstance(name, str) or not name:
        raise TypeError(
            f"expected a capability name or a decorated function, got {type(capability).__name__}"
        )
    return name
