"""
Capability registration.

See ``docs/api-reference.md §3`` and ``docs/system-design.md §2``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from execgate.annotation_inspect import (
    SignatureInfo,
    extract_description,
    find_unsupported_annotations,
    inspect_capability,
)
from execgate.schemas.infer import (
    SchemaInferenceError,
    infer_input_schema,
    infer_output_schema,
)
from execgate.schemas.types import ObjectType, Type

__all__ = ["Capability", "Registry", "build_capability"]


@dataclass(frozen=True)
class Capability:
    """
    A registered capability: the handler plus its derived contract.

    Immutable. Constructed only by ``build_capability`` and stored in a
    ``Registry``.
    """

    name: str
    description: str
    handler: Callable[..., Any]
    input_schema: ObjectType
    output_schema: Type | None
    effects: str | None = None
    requires_approval: bool = False
    idempotent: bool = False
    """When True, the executor deduplicates calls with identical
    ``(name, args_hash)`` via the engine's idempotency store. The handler
    is invoked once; subsequent calls with the same args replay the stored
    result without side effects."""
    idempotency_key: str | None = None
    """How the dedupe key is derived for an idempotent capability.

    ``None`` (default): hash of the resolved arguments, scoped to the caller's
    tenant and principal. Two *legitimate* identical calls therefore collapse
    into one; use one of the modes below for operations that may repeat.

    ``"context.request_id"``: the application-supplied ``ExecutionContext.request_id``
    (trusted, never model output) plus the step id. Fails closed if absent.

    any other string: the name of an *argument* whose value is the key. Same key
    with different arguments is an ``IDEMPOTENCY_CONFLICT``, never a silent replay."""

    def __repr__(self) -> str:
        return (
            f"Capability(name={self.name!r}, "
            f"handler={getattr(self.handler, '__name__', '<unnamed>')}, "
            f"effects={self.effects!r}, "
            f"requires_approval={self.requires_approval}, "
            f"idempotent={self.idempotent})"
        )


class Registry:
    """
    The set of capabilities registered on one engine. Names are unique.

    ``snapshot_hash()`` returns a stable digest of every capability's
    contract (not the handler). The verifier stores it in the
    ``VerifiedPlan``; the executor compares against the current hash to
    detect registry changes between verify and execute (ADR-0004).
    """

    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}
        self._snapshot_cache: str | None = None

    def add(self, capability: Capability) -> None:
        if capability.name in self._caps:
            existing = self._caps[capability.name]
            raise ValueError(
                f"capability {capability.name!r} is already registered "
                f"(existing handler: "
                f"{getattr(existing.handler, '__name__', '<unnamed>')!r})"
            )
        self._caps[capability.name] = capability
        self._snapshot_cache = None

    def unregister(self, name: str) -> None:
        if name not in self._caps:
            raise KeyError(f"unknown capability: {name!r}")
        del self._caps[name]
        self._snapshot_cache = None

    def get(self, name: str) -> Capability:
        try:
            return self._caps[name]
        except KeyError:
            raise KeyError(f"unknown capability: {name!r}") from None

    def names(self) -> list[str]:
        return list(self._caps.keys())

    def __iter__(self) -> Any:
        return iter(self._caps.values())

    def __len__(self) -> int:
        return len(self._caps)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._caps

    def snapshot_hash(self) -> str:
        if self._snapshot_cache is None:
            from execgate._internal import canonical_hash

            payload = {
                name: {
                    "input": cap.input_schema.to_json_schema(),
                    "output": (
                        cap.output_schema.to_json_schema()
                        if cap.output_schema is not None
                        else None
                    ),
                    "effects": cap.effects,
                    "requires_approval": cap.requires_approval,
                    "idempotent": cap.idempotent,
                    "idempotency_key": cap.idempotency_key,
                }
                for name, cap in self._caps.items()
            }
            self._snapshot_cache = canonical_hash(payload)
        return self._snapshot_cache


def build_capability(
    fn: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
    effects: str | None = None,
    requires_approval: bool = False,
    idempotent: bool = False,
    idempotency_key: str | None = None,
) -> Capability:
    """
    Construct a ``Capability`` from a plain Python function.

    Raises ``TypeError`` for structural or annotation problems, and
    ``ValueError`` for invalid option values. See ADR-0003.
    """
    if not callable(fn):
        raise TypeError(f"capability must be callable; got {type(fn).__name__}")

    cap_name = name if name is not None else getattr(fn, "__name__", "")
    if not isinstance(cap_name, str) or not cap_name:
        raise ValueError(f"capability name must be a non-empty string; got {cap_name!r}")

    if effects is not None and effects not in ("read", "write"):
        raise ValueError(f"effects must be 'read', 'write', or None; got {effects!r}")

    if idempotency_key is not None:
        if not idempotent:
            raise ValueError("idempotency_key requires idempotent=True")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError("idempotency_key must be a non-empty string")

    info = inspect_capability(fn)
    info = _maybe_transform_pydantic(info)

    problems = find_unsupported_annotations(info)
    if problems:
        formatted = "\n  ".join(problems)
        raise TypeError(f"cannot register capability {cap_name!r}:\n  {formatted}")

    try:
        input_schema = infer_input_schema(info.parameters)
        output_schema = infer_output_schema(info.return_annotation)
    except SchemaInferenceError as e:
        raise TypeError(f"cannot register capability {cap_name!r}: {e}") from e

    return Capability(
        name=cap_name,
        description=extract_description(fn, override=description),
        handler=fn,
        input_schema=input_schema,
        output_schema=output_schema,
        effects=effects,
        requires_approval=requires_approval,
        idempotent=idempotent,
        idempotency_key=idempotency_key,
    )


def _maybe_transform_pydantic(info: SignatureInfo) -> SignatureInfo:
    try:
        from execgate_pydantic import transform_signature
    except ImportError:
        return info
    return transform_signature(info)
