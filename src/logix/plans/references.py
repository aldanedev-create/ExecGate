"""
Reference grammar and resolution.

A ``$ref`` is the only way a step's argument can be sourced from a prior
step's output. The grammar is deliberately tiny:

    {$ref: "<step-id>.<path>"}

- ``step-id`` must match ``[A-Za-z_][A-Za-z0-9_]*``.
- ``<path>`` is a dotted sequence of segments; each segment is either a
  key name or an integer index into a list.
- No wildcards, no expressions, no functions. ``$ref`` is data, not code.

Why this matters: grounding. Sensitive arguments must be sourced from a
prior validated output, not typed by the model. When the schema layer
marks an argument as "sensitive", the verifier requires a ``$ref`` for
it, and a model cannot smuggle a fabricated value past the boundary by
inventing a literal.

See ``docs/plan-format.md §4`` and ADR-0005.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from logix.errors import Error, invalid_reference

_STEP_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SEGMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$|^\d+$")


@dataclass(frozen=True)
class Reference:
    """A parsed ``$ref`` expression."""

    step_id: str
    path: tuple[str, ...]

    def as_string(self) -> str:
        return f"{self.step_id}." + ".".join(self.path) if self.path else self.step_id


def is_reference(value: Any) -> bool:
    """True iff ``value`` is structurally a ``$ref`` expression."""
    return (
        isinstance(value, dict)
        and len(value) == 1
        and "$ref" in value
        and isinstance(value["$ref"], str)
    )


def parse_reference(value: Any) -> "Reference | Error":
    """
    Parse a ``$ref`` value into a ``Reference`` or return an ``Error``.

    Returns ``INVALID_REFERENCE`` for structural problems: wrong shape,
    bad step-id, bad path segment, empty path.
    """
    if not is_reference(value):
        return invalid_reference(
            "reference must be of the form {'$ref': '<step>.<path>'}"
        )

    raw: str = value["$ref"]
    if not raw:
        return invalid_reference("$ref must be a non-empty string")

    parts = raw.split(".")
    step_id = parts[0]
    path = tuple(parts[1:])

    if not _STEP_ID_RE.match(step_id):
        return invalid_reference(
            f"invalid step id in $ref: {step_id!r}",
            path="$ref",
        )

    for segment in path:
        if not _SEGMENT_RE.match(segment):
            return invalid_reference(
                f"invalid path segment in $ref: {segment!r}",
                path="$ref",
            )

    return Reference(step_id=step_id, path=path)


def resolve_reference(ref: Reference, results: dict[str, Any]) -> "Any | Error":
    """
    Resolve a parsed reference against already-computed step results.

    Returns the resolved value, or an ``Error`` if:
    - the referenced step has no result yet (forward reference), or
    - a path segment does not exist in that result.

    The verifier uses this at verify time against a *type-check-only*
    stub; the executor uses it at run time against real outputs.
    """
    if ref.step_id not in results:
        return invalid_reference(
            f"reference to unknown or later step: {ref.step_id!r}",
            details={"step_id": ref.step_id},
        )

    current: Any = results[ref.step_id]
    for segment in ref.path:
        if isinstance(current, dict):
            if segment not in current:
                return invalid_reference(
                    f"missing key {segment!r} at {ref.as_string()}",
                )
            current = current[segment]
        elif isinstance(current, (list, tuple)):
            try:
                idx = int(segment)
            except ValueError:
                return invalid_reference(
                    f"expected integer index at {ref.as_string()}, got {segment!r}",
                )
            if not (0 <= idx < len(current)):
                return invalid_reference(
                    f"index {idx} out of range at {ref.as_string()}",
                )
            current = current[idx]
        else:
            return invalid_reference(
                f"cannot descend into {type(current).__name__} at {ref.as_string()}",
            )
    return current