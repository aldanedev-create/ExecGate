"""
Pydantic detection and signature transformation.

Two jobs:

1. **Detect** Pydantic-related annotations in a function signature. A model
   may appear directly, inside ``Optional[...]``, inside ``list[...]``,
   inside ``dict[str, ...]``, or inside a ``Union``. All are supported.

2. **Transform** a ``SignatureInfo`` in place — every detected model (or
   container of models) becomes a ``PydanticType`` or a native ``Type``
   wrapping one. After transformation, ``find_unsupported_annotations``
   and ``infer_input_schema`` see only ``Type`` instances and pass through
   without knowing Pydantic exists.
"""

from __future__ import annotations

import typing
from typing import Any

import pydantic
from pydantic import BaseModel

from logiq.annotation_inspect import ParameterInfo, SignatureInfo
from logiq.schemas.infer import _annotation_to_type
from logiq.schemas.types import (
    UNION_ORIGINS,
    DictType,
    ListType,
    NoneType,
    UnionType,
    is_type_instance,
)
from logiq_pydantic.schema_bridge import PydanticType

HAS_PYDANTIC = True

__all__ = [
    "HAS_PYDANTIC",
    "PydanticAdapter",
    "is_pydantic_model",
    "normalize_validation_error",
    "transform_signature",
]


def is_pydantic_model(annotation: Any) -> bool:
    """True iff ``annotation`` is a ``BaseModel`` subclass (not an instance)."""
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def transform_signature(info: SignatureInfo) -> SignatureInfo:
    """
    Return a copy of ``info`` with Pydantic-aware annotations.

    Non-Pydantic annotations are left untouched. Pydantic models (and
    supported containers of them) are replaced with ``Type`` instances
    that the native schema engine understands.
    """
    new_params = tuple(
        ParameterInfo(
            name=p.name,
            annotation=_transform_annotation(p.annotation),
            default=p.default,
            has_default=p.has_default,
            kind=p.kind,
        )
        for p in info.parameters
    )
    return SignatureInfo(
        function_name=info.function_name,
        parameters=new_params,
        return_annotation=_transform_annotation(info.return_annotation),
        docstring=info.docstring,
    )


def _as_type(annotation: Any) -> Any:
    """Resolve a (possibly raw) annotation to a ``Type`` instance."""
    if is_type_instance(annotation):
        return annotation
    return _annotation_to_type(annotation)


def _transform_annotation(annotation: Any) -> Any:
    """Recursively replace Pydantic models with ``Type`` instances."""
    # Already a Type (e.g. transformed by a previous call).
    if hasattr(annotation, "validate") and hasattr(annotation, "to_json_schema"):
        return annotation

    # Direct BaseModel subclass.
    if is_pydantic_model(annotation):
        return PydanticType(annotation)

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    # Containers: only rewrite when a Pydantic model is found somewhere
    # inside. Otherwise return the annotation untouched so the native
    # schema engine infers it (leaf classes like ``int`` are not ``Type``s).

    # list[Model] / list[Optional[Model]] etc.
    if origin is list and args:
        item = _transform_annotation(args[0])
        if item is args[0]:
            return annotation
        return ListType(item_type=_as_type(item))

    # dict[str, Model]
    if origin is dict and len(args) == 2:
        # Keys must be str; leave key type alone.
        value = _transform_annotation(args[1])
        if value is args[1]:
            return annotation
        return DictType(value_type=_as_type(value))

    # Optional[Model] / Union[ModelA, ModelB] / Union[Model, None]
    if origin in UNION_ORIGINS:
        transformed_members = tuple(_transform_annotation(m) for m in args)
        if all(t is a for t, a in zip(transformed_members, args, strict=True)):
            return annotation
        members = tuple(_as_type(m) for m in transformed_members)
        non_none = [m for m in members if not isinstance(m, NoneType)]
        if len(non_none) == 1 and len(non_none) < len(members):
            return UnionType(members=(non_none[0], NoneType()))
        return UnionType(members=members)

    # Annotated[Model, ...] — leave alone; constraints on models aren't
    # supported, and Pydantic handles its own constraints via Field.
    # Recurse only into the base, preserving Annotated for the caller.
    if origin is typing.Annotated and args:
        base = _transform_annotation(args[0])
        if base is args[0]:
            return annotation  # nothing changed
        # If the base was a Pydantic model, wrap it — drop Annotated
        # metadata since Pydantic's Field is the correct place for it.
        return base

    return annotation


def normalize_validation_error(exc: pydantic.ValidationError) -> list[dict[str, Any]]:
    """
    Convert a ``ValidationError`` to a list of dicts matching the shape of
    ``logiq.schemas.SchemaError`` fields. Exposed for tests that want to
    compare shapes without importing ``SchemaError``.
    """
    return [
        {"path": _loc_to_path(err.get("loc", ())), "message": err.get("msg", "")}
        for err in exc.errors()
    ]


def _loc_to_path(loc: tuple) -> str:
    path = "$"
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


class PydanticAdapter:
    """
    Bundle of the adapter's behaviour for a caller that wants explicit
    control (e.g. ``capabilities.py``).

    A single instance is stateless and can be shared.
    """

    has_pydantic = True

    def is_enabled_for(self, annotation: Any) -> bool:
        """True if any part of ``annotation`` is a Pydantic model."""
        return _contains_pydantic(annotation)

    def transform(self, info: SignatureInfo) -> SignatureInfo:
        return transform_signature(info)


def _contains_pydantic(annotation: Any) -> bool:
    if is_pydantic_model(annotation):
        return True
    for arg in typing.get_args(annotation):
        if _contains_pydantic(arg):
            return True
    return False