"""
Plan parsing, formatting, and reference semantics.

A *plan* is untrusted JSON describing what the AI wants to do: a list of
steps, each naming a capability and supplying arguments. It is never
executable Python. The parser turns it into a normalized
``CanonicalPlan``; the verifier resolves capability names and validates
arguments; the executor runs it.

Public surface (stable 0.1):

- ``parse_plan(plan)``         — untrusted dict -> CanonicalPlan
- ``CanonicalPlan``            — parsed plan, still untrusted
- ``CanonicalStep``            — one step in a CanonicalPlan
- ``PlanLimits``               — resource limits enforced at parse time
- ``DEFAULT_LIMITS``           — documented defaults
- ``Reference``                — a $ref expression

See ``docs/plan-format.md`` and ``docs/system-design.md §2``.
"""

from __future__ import annotations

from logix.plans.format import plan_version
from logix.plans.limits import DEFAULT_LIMITS, PlanLimits
from logix.plans.parse import CanonicalPlan, CanonicalStep, parse_plan
from logix.plans.references import Reference, parse_reference

__all__ = [
    "CanonicalPlan",
    "CanonicalStep",
    "DEFAULT_LIMITS",
    "PlanLimits",
    "Reference",
    "parse_plan",
    "parse_reference",
    "plan_version",
]