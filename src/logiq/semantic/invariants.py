"""
Live-state invariants.

An invariant is a callable that receives a capability's resolved arguments
and the current ``ExecutionContext`` and returns a ``Decision`` (``Allow``,
``Deny``, or ``RequireApproval``). It is the mechanism behind
``logiq.authorize(check=...)``.

Invariants run in the recheck window, before each handler invocation.
They are allowed to read live state — database rows, external service
state, a cache — because they are the last line of defense before a side
effect.

The distinction from the static verifier: the verifier can only check
things that are functions of the plan. Invariants can check things that
are functions of the *world* at execute time.

See ``docs/semantic-layer.md`` and ADR-0004.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from logiq.errors import (
    Error, authorization_failed, policy_rejected,
)
from logiq.policies import Allow, Decision, Deny, RequireApproval

if TYPE_CHECKING:
    from logiq.context import ExecutionContext


InvariantCheck = Callable[[dict[str, Any], "ExecutionContext"], Decision]


class InvariantRegistry:
    """
    Per-engine collection of live-state checks.

    At most one check per capability in 0.1.0. Attach with ``add``; look up
    with ``get``. Registration is idempotent (later adds replace earlier ones).
    """

    def __init__(self) -> None:
        self._checks: dict[str, InvariantCheck] = {}

    def add(self, capability: str, check: InvariantCheck) -> None:
        """Attach a live-state check to a capability."""
        if not callable(check):
            raise TypeError("check must be callable")
        self._checks[capability] = check

    def get(self, capability: str) -> "InvariantCheck | None":
        return self._checks.get(capability)

    def names(self) -> list[str]:
        return sorted(self._checks.keys())


def run_invariants(
    registry: InvariantRegistry,
    capability: str,
    args: dict[str, Any],
    context: "ExecutionContext",
) -> "tuple[Decision | None, Error | None]":
    """
    Run the invariant attached to ``capability``, if any.

    Returns ``(decision, error)``:
    - ``(Allow(), None)``     — no check attached, or the check allowed.
    - ``(Deny(...), None)``   — the check denied; the caller turns it into
      an ``AUTHORIZATION_FAILED`` (or ``POLICY_REJECTED``) error.
    - ``(RequireApproval(...), None)`` — the caller routes to the approval path.
    - ``(None, Error)``       — the check raised; treated as a hard failure
      with the appropriate error code.

    Raising is treated as a denial, not a pass: a check that crashes must
    never silently allow the operation through.
    """
    check = registry.get(capability)
    if check is None:
        return Allow(), None

    try:
        decision = check(args, context)
    except Exception as e:
        # Never let a crashing check allow execution.
        return None, authorization_failed(
            f"invariant check for {capability!r} raised: {type(e).__name__}",
        )

    if isinstance(decision, (Allow, Deny, RequireApproval)):
        return decision, None
    # A check that returns something unexpected is a denial, not a pass.
    return None, authorization_failed(
        f"invariant check for {capability!r} returned invalid decision "
        f"type {type(decision).__name__}",
    )


def decision_to_error(decision: Decision) -> "Error | None":
    """Convert a non-Allow decision into a structured Error."""
    if isinstance(decision, Allow):
        return None
    if isinstance(decision, Deny):
        return policy_rejected(decision.message, details={"code": decision.code, **decision.details})
    if isinstance(decision, RequireApproval):
        # APPROVAL_REQUIRED is produced by the approval layer; this is a
        # signal to route there, not an error on its own.
        return None
    return authorization_failed("unknown decision type")