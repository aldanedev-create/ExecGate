"""
Native constraint primitives.

Constraints are attached to a base type via ``Annotated``::

    Annotated[int, Gt(0), Le(100)]
    Annotated[str, MinLength(3), Pattern(r"^[a-z]+$")]

Supported constraint kinds in 0.1.0, deliberately a small set:

- ``Gt(n)``, ``Ge(n)``, ``Lt(n)``, ``Le(n)`` — numeric range
- ``MinLength(n)``, ``MaxLength(n)`` — string or list length
- ``Pattern(regex)`` — string regex match (full match)

Any other constraint object is rejected at registration time. This is the
same "reject rather than weaken" rule as ADR-0003.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from logiq.schemas.types import SchemaError


# ---------------------------------------------------------------------------
# Constraint objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Gt:
    value: int | float
    def validate(self, value: Any, path: str) -> list[SchemaError]:
        if not value > self.value:
            return [SchemaError(path, f"must be > {self.value}")]
        return []
    def to_json_schema_fragment(self) -> dict[str, Any]:
        return {"exclusiveMinimum": self.value}


@dataclass(frozen=True)
class Ge:
    value: int | float
    def validate(self, value: Any, path: str) -> list[SchemaError]:
        if not value >= self.value:
            return [SchemaError(path, f"must be >= {self.value}")]
        return []
    def to_json_schema_fragment(self) -> dict[str, Any]:
        return {"minimum": self.value}


@dataclass(frozen=True)
class Lt:
    value: int | float
    def validate(self, value: Any, path: str) -> list[SchemaError]:
        if not value < self.value:
            return [SchemaError(path, f"must be < {self.value}")]
        return []
    def to_json_schema_fragment(self) -> dict[str, Any]:
        return {"exclusiveMaximum": self.value}


@dataclass(frozen=True)
class Le:
    value: int | float
    def validate(self, value: Any, path: str) -> list[SchemaError]:
        if not value <= self.value:
            return [SchemaError(path, f"must be <= {self.value}")]
        return []
    def to_json_schema_fragment(self) -> dict[str, Any]:
        return {"maximum": self.value}


@dataclass(frozen=True)
class MinLength:
    value: int
    def validate(self, value: Any, path: str) -> list[SchemaError]:
        if hasattr(value, "__len__") and len(value) < self.value:
            return [SchemaError(path, f"length must be >= {self.value}")]
        return []
    def to_json_schema_fragment(self) -> dict[str, Any]:
        return {"minLength": self.value}


@dataclass(frozen=True)
class MaxLength:
    value: int
    def validate(self, value: Any, path: str) -> list[SchemaError]:
        if hasattr(value, "__len__") and len(value) > self.value:
            return [SchemaError(path, f"length must be <= {self.value}")]
        return []
    def to_json_schema_fragment(self) -> dict[str, Any]:
        return {"maxLength": self.value}


@dataclass(frozen=True)
class Pattern:
    regex: str
    def validate(self, value: Any, path: str) -> list[SchemaError]:
        if isinstance(value, str) and not re.fullmatch(self.regex, value):
            return [SchemaError(path, f"does not match pattern {self.regex!r}")]
        return []
    def to_json_schema_fragment(self) -> dict[str, Any]:
        return {"pattern": self.regex}


SUPPORTED_CONSTRAINTS: tuple[type, ...] = (
    Gt, Ge, Lt, Le, MinLength, MaxLength, Pattern,
)