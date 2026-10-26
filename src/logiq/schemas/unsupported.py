"""
Unsupported annotation detection.

The single most important rule (ADR-0003): the schema engine must never
silently weaken validation. If a developer annotates a parameter with a
type that cannot be faithfully represented, registration must fail — not
fall back to ``Any``.

This module is called by ``infer.py`` for every annotation. It returns the
list of unsupported annotation descriptions, so the caller can raise a
single, complete registration error rather than failing on the first one.
"""

from __future__ import annotations

import inspect
import typing
from typing import Any

from logiq.schemas.types import UNION_ORIGINS

SUPPORTED_PRIMITIVES: frozenset[Any] = frozenset(
    {
        int,
        float,
        str,
        bool,
        type(None),
    }
)

SUPPORTED_GENERIC_ORIGINS: frozenset[Any] = frozenset(
    {
        list,
        dict,
        *UNION_ORIGINS,
    }
)

SUPPORTED_TYPING_NAMES: frozenset[str] = frozenset(
    {
        "Optional",
        "Union",
        "Literal",
    }
)


def describe_unsupported(annotation: Any) -> list[str]:
    """
    Return human-readable descriptions of every unsupported annotation in
    ``annotation``. Empty list means fully supported.

    Recurses into generics (``list[X]``, ``dict[K, V]``, ``Union[...]``)
    so a single call surfaces all problems at once.
    """
    if annotation is inspect.Parameter.empty or annotation is inspect.Signature.empty:
        return ["missing annotation"]

    # Already a resolved Type (an adapter converted it, e.g. PydanticType).
    if hasattr(annotation, "validate") and hasattr(annotation, "to_json_schema"):
        return []

    if annotation is Any or annotation is typing.Any:
        return ["typing.Any is not a validation contract; use a concrete type"]

    if annotation in SUPPORTED_PRIMITIVES:
        return []

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin is list:
        if len(args) != 1:
            return ["list must have exactly one type argument"]
        return [f"list item: {d}" for d in describe_unsupported(args[0])]

    if origin is dict:
        if len(args) != 2:
            return ["dict must have exactly two type arguments"]
        key_t, value_t = args
        problems: list[str] = []
        if key_t is not str:
            problems.append(f"dict keys must be str, got {_name(key_t)}")
        problems.extend(f"dict value: {d}" for d in describe_unsupported(value_t))
        return problems

    if origin in UNION_ORIGINS:
        problems = []
        for member in args:
            problems.extend(describe_unsupported(member))
        return problems

    if origin is typing.Literal:
        for v in args:
            if not isinstance(v, (str, int, bool, float, type(None))):
                return [f"Literal values must be primitives, got {_name(v)}"]
        has_bool = any(isinstance(v, bool) for v in args)
        has_int = any(isinstance(v, int) and not isinstance(v, bool) for v in args)
        if has_bool and has_int:
            return ["Literal cannot mix bool and int (bool is a subclass of int)"]
        return []

    if origin is typing.Annotated:
        if not args:
            return ["Annotated requires at least one argument"]
        base = args[0]
        # Constraint objects are validated by infer._annotated when the
        # schema is built; here we only check the base type.
        return describe_unsupported(base)

    return [f"unsupported annotation: {_name(annotation)}"]


def _name(annotation: Any) -> str:
    name = getattr(annotation, "__name__", None)
    if isinstance(name, str):
        return name
    return repr(annotation)
