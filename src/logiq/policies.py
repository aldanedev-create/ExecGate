"""
Policy decisions and the named-policy registry.

A policy decision is one of ``Allow``, ``Deny``, or ``RequireApproval``.
Per-capability *authorize* checks return a decision and run in the recheck
window (see ``logiq.semantic.invariants``). Named cross-cutting *policies*
are stored in ``PolicySet`` via ``logiq.policy(name, rule=...)`` and
inspected or invoked by the application.

Neither this module nor ``PolicySet`` executes anything on its own;
enforcement lives in ``verifier`` (static checks, reserved) and
``semantic.recheck`` (dynamic checks, active in 0.1.0).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from logiq.context import ExecutionContext


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------


class Decision(Protocol):
    """Marker protocol; concrete types are Allow, Deny, RequireApproval."""


@dataclass(frozen=True)
class Allow:
    """The operation is permitted by this check."""


@dataclass(frozen=True)
class Deny:
    """The operation is rejected by this check."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RequireApproval:
    """The operation requires approval before execution."""

    reason: str


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

AuthorizeCheck = Callable[[dict[str, Any], "ExecutionContext"], Decision]
"""Signature of a per-capability authorize check (used by InvariantRegistry)."""

PolicyRule = Callable[[Any, "ExecutionContext"], Decision]
"""Signature of a named policy rule. Receives a plan (any shape the rule
expects) and the current context."""


# ---------------------------------------------------------------------------
# PolicySet — the named-policy registry
# ---------------------------------------------------------------------------


class PolicySet:
    """
    Named reusable policies.

    Stores ``name -> rule`` mappings. Rules are not run automatically by
    the pipeline in 0.1.0; the application retrieves them with ``get(name)``
    or runs them all with ``decisions(plan, context)``. Per-capability
    dynamic checks — the ones the executor does run automatically — are
    registered via ``logiq.authorize(...)`` and live in ``InvariantRegistry``.

    Name uniqueness is enforced; ``add`` on an existing name raises.
    """

    def __init__(self) -> None:
        self._policies: dict[str, PolicyRule] = {}

    def add(self, name: str, rule: PolicyRule) -> None:
        """
        Register a named policy.

        Raises ``ValueError`` if the name is empty or already registered.
        Raises ``TypeError`` if ``rule`` is not callable.
        """
        if not isinstance(name, str) or not name:
            raise ValueError(f"policy name must be a non-empty string; got {name!r}")
        if not callable(rule):
            raise TypeError(f"policy rule must be callable; got {type(rule).__name__}")
        if name in self._policies:
            raise ValueError(f"policy {name!r} is already registered")
        self._policies[name] = rule

    def get(self, name: str) -> PolicyRule | None:
        """Return the policy rule, or None if absent."""
        return self._policies.get(name)

    def remove(self, name: str) -> None:
        """Remove a policy. Raises ``KeyError`` if absent."""
        if name not in self._policies:
            raise KeyError(f"unknown policy: {name!r}")
        del self._policies[name]

    def names(self) -> list[str]:
        """Registered policy names, sorted for determinism."""
        return sorted(self._policies.keys())

    def run(
        self,
        name: str,
        plan: Any,
        context: ExecutionContext,
    ) -> Decision:
        """
        Run one policy by name.

        Raises ``KeyError`` if unknown. The rule receives ``(plan, context)``.
        """
        rule = self._policies.get(name)
        if rule is None:
            raise KeyError(f"unknown policy: {name!r}")
        return rule(plan, context)

    def decisions(
        self,
        plan: Any,
        context: ExecutionContext,
    ) -> dict[str, Decision]:
        """
        Run every policy and return ``{name: decision}``.

        Useful for dry-run reporting and audit. Exceptions raised by a rule
        propagate to the caller; the caller decides whether to treat them
        as denials.
        """
        return {name: rule(plan, context) for name, rule in self._policies.items()}

    def __iter__(self) -> Iterator[tuple[str, PolicyRule]]:
        return iter(self._policies.items())

    def __len__(self) -> int:
        return len(self._policies)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._policies

    def __repr__(self) -> str:
        return f"PolicySet(names={self.names()!r})"
