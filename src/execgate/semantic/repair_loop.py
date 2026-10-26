"""
Bounded repair loop.

The application's agent loop typically looks like:

    for attempt in range(max_attempts):
        proposal = ai.propose(context)
        result = execgate.run(proposal)
        if result.ok:
            return result
        context = merge(result.errors, context)

This is the wrong shape. Two problems:

1. Unbounded attempts let a model grind.
2. The most dangerous repair is the one that routes *around* a policy:
   "the refund was denied, so I'll issue a smaller refund and a credit
   instead." A model that reads ``POLICY_REJECTED`` as a routing hint is
   exactly the failure mode we are trying to prevent.

``RepairLoop`` enforces both:

- Bounded total attempts.
- **Reroute refusal**: after a ``POLICY_REJECTED``, ``AUTHORIZATION_FAILED``,
  or ``APPROVAL_REQUIRED`` error, a subsequent plan that touches the same
  *effect class* is refused. The model may try a *different* legitimate
  operation, but not a workaround for the denied one.

The exact set of "same effect class" is derived from the registered
capabilities' ``effects`` attribute; a denial for a write-effect capability
refuses any other write-effect capability the application has not
explicitly allowed as a retry target.

See ``docs/semantic-layer.md`` and the spec's p.11 requirement.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from execgate.errors import (
    APPROVAL_REQUIRED,
    AUTHORIZATION_FAILED,
    POLICY_REJECTED,
    Error,
)

if TYPE_CHECKING:
    from execgate.capabilities import Registry


_REFUSAL_CODES: frozenset[str] = frozenset(
    {
        POLICY_REJECTED,
        AUTHORIZATION_FAILED,
        APPROVAL_REQUIRED,
    }
)


class RepairState(str, Enum):  # noqa: UP042
    ALLOWED = "allowed"
    EXHAUSTED = "exhausted"
    REFUSED = "refused"


@dataclass(frozen=True)
class RepairRefused(Exception):  # noqa: N818
    """Raised by ``RepairLoop.check_proposal`` when a repair is a reroute."""

    reason: str


@dataclass
class RepairLoop:
    """
    A bounded repair tracker.

    One instance per user request (or per logical agent turn). The
    application calls ``check_proposal`` before every ``execgate.run()``; the
    loop refuses or allows the proposal, then records the outcome.
    """

    max_attempts: int = 3
    """Total attempts allowed. Includes the first proposal."""

    registry: Registry | None = None
    """Used to classify capabilities by effect class for reroute detection."""

    _attempts: int = field(default=0, init=False)
    _denied_capabilities: set[str] = field(default_factory=set, init=False)
    _denied_effects: set[str] = field(default_factory=set, init=False)
    _last_errors: tuple[Error, ...] = field(default_factory=tuple, init=False)

    # -- public API -------------------------------------------------------

    def check_proposal(self, capabilities: Iterable[str]) -> RepairState:
        """
        Check whether a proposal that calls ``capabilities`` may proceed.

        Returns ``ALLOWED``, ``EXHAUSTED``, or ``REFUSED``. Does not consume
        an attempt — ``record_outcome`` does that.
        """
        if self._attempts >= self.max_attempts:
            return RepairState.EXHAUSTED

        for cap in capabilities:
            if cap in self._denied_capabilities:
                return RepairState.REFUSED
            effect = self._effect_of(cap)
            if effect is not None and effect in self._denied_effects:
                return RepairState.REFUSED

        return RepairState.ALLOWED

    def record_outcome(self, errors: tuple[Error, ...] | list[Error]) -> None:
        """Record the result of an attempt. Called after every ``execgate.run``."""
        self._attempts += 1
        self._last_errors = tuple(errors)
        # Extract refusal codes and remember denied capabilities / effects
        # from their ``details`` when available.
        for error in self._last_errors:
            if error.code not in _REFUSAL_CODES:
                continue
            cap = error.details.get("capability")
            if isinstance(cap, str):
                self._denied_capabilities.add(cap)
                effect = self._effect_of(cap)
                if effect is not None:
                    self._denied_effects.add(effect)

    # -- introspection ----------------------------------------------------

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def exhausted(self) -> bool:
        return self._attempts >= self.max_attempts

    @property
    def last_errors(self) -> tuple[Error, ...]:
        return self._last_errors

    # -- internals --------------------------------------------------------

    def _effect_of(self, capability: str) -> str | None:
        if self.registry is None:
            return None
        try:
            cap = self.registry.get(capability)
        except KeyError:
            return None
        return getattr(cap, "effects", None)


def assert_repair_allowed(loop: RepairLoop, capabilities: Iterable[str]) -> None:
    """
    Convenience for application code:

        assert_repair_allowed(loop, ["issue_refund"])

    Raises ``RepairRefused`` if the proposal would reroute around a prior
    refusal. The raised message is safe to log (no arguments, no secrets).
    """
    state = loop.check_proposal(capabilities)
    if state is RepairState.EXHAUSTED:
        raise RepairRefused("repair attempts exhausted")
    if state is RepairState.REFUSED:
        raise RepairRefused("proposal would reroute around a prior policy or authorization refusal")
