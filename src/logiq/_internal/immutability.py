"""
Immutability helpers.

Three problems this module solves, all of which the trust boundary depends on:

1. **Freezing** — a ``dict`` becomes a ``MappingProxyType`` and a ``list``
   becomes a ``tuple``, recursively. Once frozen, no caller can mutate the
   value between verify and execute. ``ir.VerifiedPlan`` relies on this.

2. **Canonical JSON** — a deterministic serialization of a JSON-compatible
   value regardless of key insertion order. Used for hashing.

3. **Canonical hashing** — a SHA-256 digest of the canonical JSON. Used for
   ``VerifiedPlan.verification_hash``, ``ApprovalToken.args_hash``, and
   capability snapshot hashes. Any two equal payloads hash identically.

``freeze`` and ``thaw`` round-trip. ``is_frozen`` is for tests and for
defensive assertions.
"""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Any

# ---------------------------------------------------------------------------
# Freezing and thawing
# ---------------------------------------------------------------------------


def freeze(value: Any) -> Any:
    """
    Recursively freeze a JSON-compatible value.

    - ``dict``  -> ``MappingProxyType`` (read-only view)
    - ``list``  -> ``tuple``
    - ``set``   -> ``frozenset``
    - ``tuple`` -> ``tuple`` of frozen elements
    - other     -> returned unchanged

    Idempotent: freezing an already-frozen value returns it unchanged.
    """
    if isinstance(value, MappingProxyType):
        return value
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze(v) for v in value)
    return value


def thaw(value: Any) -> Any:
    """
    Reverse ``freeze``: return a mutable, JSON-serializable copy.

    - ``MappingProxyType`` -> ``dict``
    - ``tuple``            -> ``list``
    - ``frozenset``        -> ``list`` (sorted, for determinism)
    """
    if isinstance(value, MappingProxyType):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, dict):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [thaw(v) for v in sorted(value, key=repr)]
    return value


def is_frozen(value: Any) -> bool:
    """
    True iff ``value`` is fully frozen (all nested containers are immutable).

    Useful in tests: ``assert is_frozen(verified_plan.serialize())`` when
    the plan's internal representation should not be mutatable.
    """
    if isinstance(value, MappingProxyType):
        return all(is_frozen(v) for v in value.values())
    if isinstance(value, tuple):
        return all(is_frozen(v) for v in value)
    if isinstance(value, frozenset):
        return all(is_frozen(v) for v in value)
    return not isinstance(value, (dict, list, set))


# ---------------------------------------------------------------------------
# Canonical JSON and hashing
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """
    Deterministic JSON serialization.

    Keys sorted, no whitespace, primitives only. Frozen containers are
    thawed transparently. Non-JSON primitives are stringified via
    ``default=str`` so hashing never fails on unknown leaves — a
    non-serializable value produces a hash of its ``str`` form, which is
    stable within a process. Callers that care about cross-process
    stability should pass JSON-compatible values only.
    """
    return json.dumps(
        thaw(value),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=False,
    )


def canonical_hash(value: Any) -> str:
    """
    SHA-256 hex digest of ``canonical_json(value)``.

    Two equal payloads produce equal digests regardless of key order or
    insertion history. This is the primitive used by:

    - ``VerifiedPlan.verification_hash``
    - ``VerifiedPlan.capability_snapshot_hash``
    - ``ApprovalToken.args_hash``
    - any cache-invalidation key the verifier computes
    """
    payload = canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assert_immutable(value: Any, name: str = "value") -> None:
    """
    Raise ``TypeError`` if ``value`` is not fully frozen.

    For use in post-construction checks inside ``ir.py`` and the executor.
    ``assert_immutable(v, "step_arguments")`` reads better than three
    nested ``isinstance`` calls.
    """
    if not is_frozen(value):
        raise TypeError(
            f"{name} must be immutable (freeze() it before storing); got a mutable container"
        )
