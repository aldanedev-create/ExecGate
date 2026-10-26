"""
Resource limits enforced at parse time.

These are *structural* limits: they bound the plan's shape before any
capability is resolved. They are the first line of defense against a
malicious or runaway plan; the verifier and executor enforce their own
limits (step count, invocation count) in addition.

Defaults are documented in ``docs/production-guide.md`` and must not be
changed without a changelog entry — applications and tests rely on them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanLimits:
    """Resource limits for a single plan."""

    max_bytes: int = 64_000
    """Maximum serialized size of the input plan, in bytes."""

    max_steps: int = 32
    """Maximum number of steps in a plan."""

    max_depth: int = 8
    """Maximum nesting depth of any JSON value in the plan."""

    max_invocations: int = 64
    """Maximum total handler invocations (>= max_steps to allow repeats)."""

    def check_bytes(self, n: int) -> None:
        """Raise ``ValueError`` if ``n`` exceeds ``max_bytes``."""
        if n > self.max_bytes:
            raise ValueError(f"plan exceeds max_bytes ({n} > {self.max_bytes})")

    def check_steps(self, n: int) -> None:
        if n > self.max_steps:
            raise ValueError(f"plan exceeds max_steps ({n} > {self.max_steps})")

    def check_depth(self, n: int) -> None:
        if n > self.max_depth:
            raise ValueError(f"plan exceeds max_depth ({n} > {self.max_depth})")


DEFAULT_LIMITS = PlanLimits()
