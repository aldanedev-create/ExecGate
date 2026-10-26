"""
Value validation against a ``Type`` plus attached constraints.

Two entry points:

- ``validate_input(schema, value)`` — validate arguments before a handler runs.
- ``validate_output(schema, value)`` — validate a handler's return value.

Both return a list of ``SchemaError`` (empty means valid). The caller is
responsible for translating those into ``execgate.errors.Error`` with the
proper code (``SCHEMA_VALIDATION_FAILED`` at input, ``OUTPUT_VALIDATION_FAILED``
at output) so the public error code differs but the underlying check is the
same.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from execgate.schemas.types import SchemaError, Type


@dataclass(frozen=True)
class ConstrainedType:
    """A base type plus a list of constraint objects to run after the base check."""

    base: Type
    constraints: tuple[Any, ...]

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        errors = self.base.validate(value, path)
        if errors:
            return errors
        for constraint in self.constraints:
            errors.extend(constraint.validate(value, path))
        return errors

    def to_json_schema(self) -> dict[str, Any]:
        schema = dict(self.base.to_json_schema())
        for constraint in self.constraints:
            schema.update(constraint.to_json_schema_fragment())
        return schema

    def walk(self, segment: str) -> Type | None:
        return self.base.walk(segment)


def validate_input(schema: Type, value: Any) -> list[SchemaError]:
    """Validate an argument value against its declared input schema."""
    return schema.validate(value, path="$")


def validate_output(schema: Type, value: Any) -> list[SchemaError]:
    """Validate a handler return value against its declared output schema."""
    return schema.validate(value, path="$")
