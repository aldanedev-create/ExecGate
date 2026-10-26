"""
Grounding: sensitive arguments must be sourced from trusted data.

The core semantic hallucination is the model asserting a fact that is not
true: "the order is refundable for $50" becomes
``{"order_id": 502, "amount": 50.0}``. A schema-valid argument map cannot
prevent this because the argument *is* the hallucination.

The grounding rule is:

> A sensitive argument must be sourced from a ``$ref`` to an earlier
> validated handler output, or from an explicit literal allowlist that the
> developer declared. It must not be a free-form value the model typed.

Applied at *verify* time (it is a static property of the plan). A plan
that violates grounding is rejected before any handler runs.

See ``docs/semantic-layer.md`` and ADR-0005.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

from logiq.errors import Error, grounding_required
from logiq.plans.parse import CanonicalPlan, CanonicalStep
from logiq.plans.references import is_reference

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class GroundingPolicy:
    """
    Per-capability, per-argument grounding rules.

    Paths are ``"<capability>.<argument>"``. Nested arguments are addressed
    with dotted paths, e.g. ``"issue_refund.line_items.0.amount"``.

    - ``require_ref``   — paths whose value must be a ``$ref`` expression.
    - ``literal_allowlist`` — paths whose value MAY be a literal even if
      sensitive (e.g. a user-supplied value the application has already
      validated). Overrides ``require_ref`` for the same path.
    """

    require_ref: frozenset[str] = field(default_factory=frozenset)
    literal_allowlist: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # Every path must look like "capability.something".
        for path in self.require_ref | self.literal_allowlist:
            if "." not in path or path.startswith(".") or path.endswith("."):
                raise ValueError(
                    f"grounding path must be 'capability.argument': {path!r}"
                )


def check_grounding(
    plan: CanonicalPlan,
    policy: GroundingPolicy,
) -> list[Error]:
    """
    Validate every sensitive argument in ``plan`` against ``policy``.

    Returns ``GROUNDING_REQUIRED`` errors for each sensitive argument that
    is a bare literal and not on the allowlist. Empty list means the plan
    is grounded.
    """
    if not policy.require_ref:
        return []

    errors: list[Error] = []

    for idx, step in enumerate(plan.steps):
        step_prefix = f"steps[{idx}]" if not plan.single_call else "with"
        for arg_path, value in _walk_args(step.arguments):
            full_path = f"{step.capability}.{arg_path}"
            if full_path not in policy.require_ref:
                continue
            if full_path in policy.literal_allowlist:
                continue
            if is_reference(value):
                continue
            errors.append(grounding_required(
                f"argument {full_path!r} must be sourced from a $ref "
                f"(not a literal value)",
                path=f"{step_prefix}.{arg_path}",
                details={"capability": step.capability, "argument": arg_path},
            ))

    return errors


def _walk_args(args: dict, prefix: str = "") -> Iterable[tuple[str, object]]:
    """Yield (dotted_path, value) for every leaf argument."""
    for k, v in args.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and not is_reference(v):
            yield from _walk_args(v, path)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                item_path = f"{path}.{i}"
                if isinstance(item, dict) and not is_reference(item):
                    yield from _walk_args(item, item_path)
                else:
                    yield item_path, item
        else:
            yield path, v