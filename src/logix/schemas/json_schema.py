"""
JSON Schema export.

The same ``Type`` object that validates at runtime also emits JSON Schema
for the AI catalog. This is the "one schema, two uses" rule: the catalog
and the verifier never disagree about what an argument must be.

The output is dialect-agnostic JSON Schema: ``type``, ``properties``,
``required``, ``additionalProperties``, ``items``, ``enum``, ``anyOf``,
and the constraint keywords from ``constraints.py``.
"""

from __future__ import annotations

from typing import Any

from logix.schemas.types import Type


def to_json_schema(schema: "Type | None") -> dict[str, Any]:
    """Convert a ``Type`` to a JSON Schema dict. ``None`` means ``{}``."""
    if schema is None:
        return {}
    return schema.to_json_schema()


def capability_json_schema(
    input_schema: Type,
    output_schema: "Type | None",
) -> dict[str, Any]:
    """The full description published to the AI catalog for one capability."""
    return {
        "input_schema": to_json_schema(input_schema),
        "output_schema": to_json_schema(output_schema) if output_schema else None,
    }