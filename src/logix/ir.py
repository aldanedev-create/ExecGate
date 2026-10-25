"""
The verified intermediate representation.

``VerifiedPlan`` is the only object the executor accepts. It is
constructed only by the verifier; it is frozen and cannot be mutated or
forged from a plain dict.

This is the structural guarantee described in
``docs/system-design.md §11``: the executor does not accept anything that
merely *claims* to be verified.

Construction is deliberately not exported. ``_construct_verified_plan``
lives here but is called only by ``logix.verifier``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


__all__ = ["VerifiedStep", "VerifiedPlan"]  # _construct_verified_plan is private


@dataclass(frozen=True)
class VerifiedStep:
    """One normalized, verified step. Contains no executable code."""

    id: str
    capability: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Freeze the argument map so it cannot be mutated between verify
        # and execute. Nested containers are frozen by the parser; here we
        # only guard the top level of this step's map.
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))

    def serialize(self) -> dict[str, Any]:
        return {"id": self.id, "call": self.capability, "with": dict(self.arguments)}


@dataclass(frozen=True, init=False)
class VerifiedPlan:
    """
    A plan that has passed static verification.

    Constructed only by ``logix.verifier``. The ``init=False`` and the
    module-private constructor below are the enforcement: no user code can
    produce a ``VerifiedPlan`` by calling the dataclass directly.

    ``single_call`` records whether the plan was parsed from the concise
    ``{"call": ..., "with": ...}`` form. The executor uses it to decide
    whether to return the single handler value or a ``{step_id: output}``
    map; the verifier sets it from ``CanonicalPlan.single_call``.

    A ``VerifiedPlan`` is *not* an authorization grant. ``execute()``
    re-runs the dynamic checks (ADR-0004).
    """

    plan_version: str
    steps: tuple[VerifiedStep, ...]
    dependency_order: tuple[str, ...]
    capability_snapshot_hash: str
    verification_hash: str
    single_call: bool

    def serialize(self) -> dict[str, Any]:
        """Serialize for audit. Re-entering the pipeline requires verify()."""
        return {
            "plan_version": self.plan_version,
            "steps": [s.serialize() for s in self.steps],
            "dependency_order": list(self.dependency_order),
            "capability_snapshot_hash": self.capability_snapshot_hash,
            "verification_hash": self.verification_hash,
            "single_call": self.single_call,
        }


def _construct_verified_plan(
    *,
    plan_version: str,
    steps: tuple[VerifiedStep, ...],
    dependency_order: tuple[str, ...],
    capability_snapshot_hash: str,
    verification_hash: str,
    single_call: bool,
) -> VerifiedPlan:
    """
    Private constructor. Called only by ``logix.verifier``.

    Do not export this from ``logix``. Do not add a public factory on
    ``VerifiedPlan``. ADR-0002.

    ``single_call`` is required (no default) so a caller that forgets to
    pass it gets a ``TypeError`` at the construction site rather than
    silently creating a plan with the wrong result shape.
    """
    obj = object.__new__(VerifiedPlan)
    object.__setattr__(obj, "plan_version", plan_version)
    object.__setattr__(obj, "steps", steps)
    object.__setattr__(obj, "dependency_order", dependency_order)
    object.__setattr__(obj, "capability_snapshot_hash", capability_snapshot_hash)
    object.__setattr__(obj, "verification_hash", verification_hash)
    object.__setattr__(obj, "single_call", single_call)
    return obj