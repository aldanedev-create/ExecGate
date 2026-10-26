"""
Schema inference from Python annotations.

Turns a ``SignatureInfo`` (from ``annotation_inspect``) into an
``ObjectType`` describing the capability's input, and a ``Type | None``
for its output.

Unsupported annotations cause inference to return errors; registration
fails loudly rather than silently weakening validation (ADR-0003).

This module does not resolve ``from __future__ import annotations`` string
forms; the caller (``annotation_inspect``) resolves them via
``typing.get_type_hints`` and surfaces unresolved ones before this module
runs.
"""

from __future__ import annotations

import typing
from typing import Any

from execgate.schemas.constraints import (
    SUPPORTED_CONSTRAINTS,
)
from execgate.schemas.types import (
    UNION_ORIGINS,
    AnyType,
    BoolType,
    DictType,
    FloatType,
    IntType,
    ListType,
    LiteralType,
    NoneType,
    ObjectType,
    StrType,
    Type,
    UnionType,
    is_type_instance,
)
from execgate.schemas.unsupported import describe_unsupported
from execgate.schemas.validate import ConstrainedType


class SchemaInferenceError(ValueError):
    """Raised when an annotation cannot be faithfully represented."""


def infer_input_schema(
    parameters: tuple[Any, ...],
    *,
    namespace: dict[str, Any] | None = None,
) -> ObjectType:
    """
    Build an ``ObjectType`` for a capability's parameters.

    Raises
    ------
    SchemaInferenceError
        With a message listing every unsupported annotation. All problems
        are reported at once, not the first one found.
    """
    fields: dict[str, Type] = {}
    required: set[str] = set()
    problems: list[str] = []

    for param in parameters:
        annotation = _resolve(param.annotation, namespace)

        # Already a resolved Type (adapter transformed it).
        if is_type_instance(annotation):
            if param.has_default:
                if param.default is None and not _allows_none_in_type(annotation):
                    problems.append(
                        f"parameter {param.name!r}: default is None but annotation "
                        f"does not allow None; use Optional[...]"
                    )
                    continue
            else:
                required.add(param.name)
            fields[param.name] = annotation
            continue

        param_problems = describe_unsupported(annotation)
        if param_problems:
            problems.extend(f"parameter {param.name!r}: {p}" for p in param_problems)
            continue

        field_type = _annotation_to_type(annotation)

        if param.has_default:
            if param.default is None and not _allows_none(annotation):
                problems.append(
                    f"parameter {param.name!r}: default is None but annotation "
                    f"does not allow None; use Optional[...]"
                )
                continue
        else:
            required.add(param.name)

        fields[param.name] = field_type

    if problems:
        raise SchemaInferenceError("unsupported annotations:\n  " + "\n  ".join(problems))

    return ObjectType(fields=fields, required=frozenset(required))


def infer_output_schema(
    return_annotation: Any,
    *,
    namespace: dict[str, Any] | None = None,
) -> Type | None:
    """
    Build the output ``Type``, or None when the return is unannotated.

    Returning None means "no output validation declared"; the executor
    will skip output validation. It does NOT mean "accept anything" —
    callers that need a contract must annotate the return.
    """
    import inspect

    if return_annotation is inspect.Signature.empty:
        return None

    annotation = _resolve(return_annotation, namespace)

    if is_type_instance(annotation):
        return annotation  # type: ignore[no-any-return]

    problems = describe_unsupported(annotation)
    if problems:
        raise SchemaInferenceError("unsupported return annotation:\n  " + "\n  ".join(problems))
    return _annotation_to_type(annotation)


# ---------------------------------------------------------------------------
# Annotation -> Type
# ---------------------------------------------------------------------------


def _annotation_to_type(annotation: Any) -> Type:
    # Already a resolved Type (adapter transformed it, e.g. PydanticType).
    if is_type_instance(annotation):
        return annotation  # type: ignore[no-any-return]

    if annotation is int:
        return IntType()
    if annotation is float:
        return FloatType()
    if annotation is str:
        return StrType()
    if annotation is bool:
        return BoolType()
    if annotation is type(None):
        return NoneType()
    if annotation is Any or annotation is typing.Any:
        return AnyType()

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin is list:
        return ListType(item_type=_annotation_to_type(args[0]))
    if origin is dict:
        return DictType(value_type=_annotation_to_type(args[1]))
    if origin in UNION_ORIGINS:
        return _union_or_optional(args)
    if origin is typing.Literal:
        return LiteralType(values=tuple(args))
    if origin is typing.Annotated:
        return _annotated(args)

    raise SchemaInferenceError(f"unsupported annotation: {annotation!r}")


def _union_or_optional(members: tuple[Any, ...]) -> Type:
    non_none = [m for m in members if m is not type(None)]
    has_none = len(non_none) < len(members)
    if has_none and len(non_none) == 1:
        return UnionType(members=(_annotation_to_type(non_none[0]), NoneType()))
    return UnionType(members=tuple(_annotation_to_type(m) for m in members))


def _annotated(args: tuple[Any, ...]) -> Type:
    base = _annotation_to_type(args[0])
    constraints: list[Any] = []
    for meta in args[1:]:
        if isinstance(meta, SUPPORTED_CONSTRAINTS):
            constraints.append(meta)
        else:
            raise SchemaInferenceError(f"unsupported constraint on Annotated: {meta!r}")
    if constraints:
        return ConstrainedType(base=base, constraints=tuple(constraints))
    return base


def _resolve(annotation: Any, namespace: dict[str, Any] | None) -> Any:
    """Resolve a string annotation using the given namespace, if any."""
    if isinstance(annotation, str) and namespace is not None:
        try:
            return eval(annotation, namespace)
        except Exception:
            return annotation
    return annotation


def _allows_none(annotation: Any) -> bool:
    if annotation is type(None):
        return True
    origin = typing.get_origin(annotation)
    if origin in UNION_ORIGINS:
        return any(_allows_none(m) for m in typing.get_args(annotation))
    if origin is typing.Annotated:
        return _allows_none(typing.get_args(annotation)[0])
    return False


def _allows_none_in_type(schema_type: Type) -> bool:
    """True if a resolved ``Type`` accepts None."""
    if isinstance(schema_type, NoneType):
        return True
    if isinstance(schema_type, UnionType):
        return any(_allows_none_in_type(m) for m in schema_type.members)
    return False
