"""
The schema type system.

A ``Type`` describes what a value must be. The strict semantics here are
the entire point of ADR-0003: ``bool`` is not an ``int``, integers are not
silently coerced to floats, and a value either matches its declared type
or is rejected. No implicit coercion anywhere.

Every ``Type`` implements three methods:

- ``validate(value, path) -> list[SchemaError]``
- ``to_json_schema() -> dict``
- ``walk(segment) -> Type | None`` — navigate a reference path through
  this type. Used by the verifier for ``$ref`` type-checking, so it works
  uniformly across native types and adapter types (Pydantic).
"""

from __future__ import annotations

import types as _types
import typing as _typing
from dataclasses import dataclass
from typing import Any, Protocol

# ``typing.Union[X, None]`` and PEP 604 ``X | None`` have different
# ``get_origin`` results on Python 3.11-3.13 (unified only in 3.14).
UNION_ORIGINS: tuple[Any, ...] = (_typing.Union, _types.UnionType)


# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SchemaError:
    """A single schema validation failure at a specific path."""

    path: str
    message: str
    code: str = "SCHEMA_VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# Type protocol
# ---------------------------------------------------------------------------

class Type(Protocol):
    def validate(self, value: Any, path: str = "$") -> list[SchemaError]: ...
    def to_json_schema(self) -> dict[str, Any]: ...
    def walk(self, segment: str) -> "Type | None": ...


def is_type_instance(value: Any) -> bool:
    """
    True if ``value`` structurally implements the ``Type`` protocol.

    Used by ``unsupported`` and ``infer`` to recognize values that an
    adapter (e.g. ``logiq_pydantic``) has already resolved to a schema,
    so they are not rejected as unsupported annotations.
    """
    return (
        hasattr(value, "validate")
        and hasattr(value, "to_json_schema")
        and hasattr(value, "walk")
    )


# ---------------------------------------------------------------------------
# Primitive types — strict, no coercion
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntType:
    """Strict integer. ``True`` and ``1.0`` are rejected; only ``int`` (not ``bool``)."""

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        if isinstance(value, bool) or not isinstance(value, int):
            return [SchemaError(path, f"expected int, got {_name_of(value)}")]
        return []

    def to_json_schema(self) -> dict[str, Any]:
        return {"type": "integer"}

    def walk(self, segment: str) -> "Type | None":
        return None


@dataclass(frozen=True)
class FloatType:
    """Strict float. Rejects ints (no implicit widening) and bools."""

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        if isinstance(value, bool) or not isinstance(value, float):
            return [SchemaError(path, f"expected float, got {_name_of(value)}")]
        return []

    def to_json_schema(self) -> dict[str, Any]:
        return {"type": "number"}

    def walk(self, segment: str) -> "Type | None":
        return None


@dataclass(frozen=True)
class NumberType:
    """Any JSON number: int or float, but not bool."""

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [SchemaError(path, f"expected number, got {_name_of(value)}")]
        return []

    def to_json_schema(self) -> dict[str, Any]:
        return {"type": "number"}

    def walk(self, segment: str) -> "Type | None":
        return None


@dataclass(frozen=True)
class StrType:
    """Strict string. No bytes, no enum coercion."""

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        if not isinstance(value, str):
            return [SchemaError(path, f"expected str, got {_name_of(value)}")]
        return []

    def to_json_schema(self) -> dict[str, Any]:
        return {"type": "string"}

    def walk(self, segment: str) -> "Type | None":
        return None


@dataclass(frozen=True)
class BoolType:
    """Strict bool. Rejects 0/1 and '' (no truthiness coercion)."""

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        if not isinstance(value, bool):
            return [SchemaError(path, f"expected bool, got {_name_of(value)}")]
        return []

    def to_json_schema(self) -> dict[str, Any]:
        return {"type": "boolean"}

    def walk(self, segment: str) -> "Type | None":
        return None


@dataclass(frozen=True)
class NoneType:
    """The value ``None``."""

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        if value is not None:
            return [SchemaError(path, f"expected null, got {_name_of(value)}")]
        return []

    def to_json_schema(self) -> dict[str, Any]:
        return {"type": "null"}

    def walk(self, segment: str) -> "Type | None":
        return None


# ---------------------------------------------------------------------------
# Container types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnyType:
    """Explicit opt-in escape hatch. Not produced by inference."""

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        return []

    def to_json_schema(self) -> dict[str, Any]:
        return {}

    def walk(self, segment: str) -> "Type | None":
        return None


@dataclass(frozen=True)
class ListType:
    """A homogeneous list. Each item validated against ``item_type``."""

    item_type: Type

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        if not isinstance(value, list):
            return [SchemaError(path, f"expected list, got {_name_of(value)}")]
        errors: list[SchemaError] = []
        for i, item in enumerate(value):
            errors.extend(self.item_type.validate(item, f"{path}[{i}]"))
        return errors

    def to_json_schema(self) -> dict[str, Any]:
        return {"type": "array", "items": self.item_type.to_json_schema()}

    def walk(self, segment: str) -> "Type | None":
        try:
            int(segment)
        except ValueError:
            return None
        return self.item_type


@dataclass(frozen=True)
class DictType:
    """A string-keyed dict with a declared value type."""

    value_type: Type

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        if not isinstance(value, dict):
            return [SchemaError(path, f"expected dict, got {_name_of(value)}")]
        errors: list[SchemaError] = []
        for k, v in value.items():
            if not isinstance(k, str):
                errors.append(SchemaError(path, f"dict keys must be str, got {_name_of(k)}"))
                continue
            errors.extend(self.value_type.validate(v, f"{path}.{k}"))
        return errors

    def to_json_schema(self) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": self.value_type.to_json_schema()}

    def walk(self, segment: str) -> "Type | None":
        return self.value_type


@dataclass(frozen=True)
class ObjectType:
    """
    A structured object with declared fields.

    Unknown fields are rejected by default (``additional=False``). This is
    the default because silently ignoring extra fields is exactly how a
    malicious model smuggles state past validation.
    """

    fields: dict[str, Type]
    required: frozenset[str] = frozenset()
    additional: bool = False

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        if not isinstance(value, dict):
            return [SchemaError(path, f"expected object, got {_name_of(value)}")]
        errors: list[SchemaError] = []

        if not self.additional:
            unknown = set(value.keys()) - set(self.fields.keys())
            for k in sorted(unknown):
                errors.append(SchemaError(f"{path}.{k}", "unknown field"))

        for name in self.required:
            if name not in value:
                errors.append(SchemaError(f"{path}.{name}", "missing required field"))

        for name, ftype in self.fields.items():
            if name in value:
                errors.extend(ftype.validate(value[name], f"{path}.{name}"))

        return errors

    def to_json_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {k: v.to_json_schema() for k, v in self.fields.items()},
            "required": sorted(self.required),
            "additionalProperties": self.additional,
        }

    def walk(self, segment: str) -> "Type | None":
        return self.fields.get(segment)


@dataclass(frozen=True)
class LiteralType:
    """An enum of exact values. ``Literal["a", "b"]`` or ``Literal[1, 2, 3]``."""

    values: tuple[Any, ...]

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        for expected in self.values:
            if type(value) is type(expected) and value == expected:
                return []
        allowed = ", ".join(repr(v) for v in self.values)
        return [SchemaError(path, f"expected one of {{{allowed}}}, got {value!r}")]

    def to_json_schema(self) -> dict[str, Any]:
        return {"enum": list(self.values)}

    def walk(self, segment: str) -> "Type | None":
        return None


@dataclass(frozen=True)
class UnionType:
    """A value must match at least one member type."""

    members: tuple[Type, ...]

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        best_errors: list[SchemaError] | None = None
        for member in self.members:
            errs = member.validate(value, path)
            if not errs:
                return []
            if best_errors is None or len(errs) < len(best_errors):
                best_errors = errs
        return best_errors or [SchemaError(path, "value matched no union member")]

    def to_json_schema(self) -> dict[str, Any]:
        return {"anyOf": [m.to_json_schema() for m in self.members]}

    def walk(self, segment: str) -> "Type | None":
        members = [m.walk(segment) for m in self.members]
        if any(m is None for m in members):
            return None
        first = members[0]
        # All members must resolve to structurally identical leaves for the
        # walk to be unambiguous. Equality on frozen dataclasses is
        # structural, which is exactly what we want.
        if not all(m == first for m in members[1:]):
            return None
        return first


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _name_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__