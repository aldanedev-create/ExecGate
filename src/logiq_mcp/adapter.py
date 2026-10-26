"""
Data shaping between Logix and MCP.

Everything here is pure translation: JSON Schema in, JSON Schema out; a
``Result`` in, a value or ``ToolError`` out. No FastMCP import at module
level, so the functions can be tested without FastMCP installed — the
same discipline as ``logiq_ai.neutral``.

The MCP ``Tool`` shape (as of the MCP spec) is::

    {"name": str, "description": str | None, "inputSchema": dict}

which maps almost one-to-one to ``logiq.tools.ToolSpec``. The two
non-trivial conversions are:

- ``mcp_schema_to_logix`` — reverse: MCP ``inputSchema`` -> Logix
  ``ObjectType``, used by the proxy to wrap upstream tools as native
  capabilities.
- ``result_to_mcp_response`` — forward: ``Result`` -> whatever FastMCP's
  tool handler returns (value on success, ``ToolError`` on failure).
"""

from __future__ import annotations

import json
from typing import Any

from logiq.errors import Error
from logiq.results import Result
from logiq.schemas.types import (
    AnyType,
    BoolType,
    FloatType,
    IntType,
    ListType,
    LiteralType,
    NoneType,
    NumberType,
    ObjectType,
    SchemaError,
    StrType,
    Type,
    UnionType,
)
from logiq.tools import ToolSpec

__all__ = [
    "extract_mcp_result_value",
    "format_errors_for_mcp",
    "from_mcp_call",
    "mcp_schema_to_logix",
    "result_to_mcp_response",
    "tool_spec_to_mcp_dict",
]


# ---------------------------------------------------------------------------
# ToolSpec -> MCP tool definition
# ---------------------------------------------------------------------------

def tool_spec_to_mcp_dict(spec: ToolSpec) -> dict[str, Any]:
    """
    Convert a ``ToolSpec`` to an MCP ``tools/list`` entry.

    The neutral and MCP shapes are nearly identical; the only difference
    is the field name (``input_schema`` vs ``inputSchema``).
    """
    return {
        "name": spec.name,
        "description": spec.description,
        "inputSchema": spec.input_schema,
    }


# ---------------------------------------------------------------------------
# MCP call -> neutral plan
# ---------------------------------------------------------------------------

def from_mcp_call(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """
    Convert an MCP ``tools/call`` (name + arguments) into a neutral plan.

    Args:
        name: the MCP tool name. Must exactly match a capability name.
        arguments: the arguments dict from the MCP request. MCP servers
            commonly send ``None`` for tools with no parameters; that is
            treated as ``{}``.

    Returns:
        A single-call plan dict suitable for ``logiq.verify()`` /
        ``logiq.run()``.

    Note: this does NOT mark anything verified. The plan flows through
    the full Logix pipeline: parse, grounding, verify, recheck, execute.
    """
    return {"call": name, "with": dict(arguments or {})}


# ---------------------------------------------------------------------------
# Result -> MCP response
# ---------------------------------------------------------------------------

def result_to_mcp_response(result: Result) -> Any:
    """
    Convert a ``Result`` to what a FastMCP tool handler should return.

    On success: returns ``result.value``. FastMCP serializes it as text
    content (or passes it through if already MCP-shaped).

    On failure: raises ``fastmcp.exceptions.ToolError`` with a formatted
    message. FastMCP converts that to a ``CallToolResult`` with
    ``isError=True`` and the message as text content. This is the
    documented FastMCP contract — returning a raw ``CallToolResult`` from
    a tool function is not portable across FastMCP minor versions, so we
    let FastMCP own the error shape.
    """
    from fastmcp.exceptions import ToolError

    if result.ok:
        return result.value
    raise ToolError(format_errors_for_mcp(result.errors))


def format_errors_for_mcp(errors: tuple[Error, ...]) -> str:
    """
    Format ``Result.errors`` as a single human-readable string for MCP.

    One line per error, with code and optional path. Kept simple and
    safe — no stack traces, no raw argument values (which would have been
    redacted upstream anyway).
    """
    lines: list[str] = []
    for e in errors:
        path_part = f" (at {e.path})" if e.path else ""
        lines.append(f"[{e.code}] {e.message}{path_part}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP CallToolResult -> plain value (for the proxy)
# ---------------------------------------------------------------------------

def extract_mcp_result_value(call_result: Any) -> Any:
    """
    Extract a JSON-compatible value from an MCP ``CallToolResult``.

    MCP responses carry a list of content blocks; text blocks have
    ``.text``. We join all text blocks and try to JSON-decode the result.
    If decoding fails, return the raw string. If there is no text content,
    return ``None``.

    This is what a proxy handler returns as its "upstream result".
    """
    if call_result is None:
        return None

    texts: list[str] = []
    content = getattr(call_result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            texts.append(text)

    if not texts:
        return None

    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return joined


# ---------------------------------------------------------------------------
# MCP inputSchema (JSON Schema) -> Logix ObjectType
# ---------------------------------------------------------------------------

def mcp_schema_to_logix(schema: dict[str, Any]) -> ObjectType:
    """
    Convert an MCP ``inputSchema`` (JSON Schema) to a Logix ``ObjectType``.

    MCP tools always accept an object at the top level, so the result is
    always an ``ObjectType``. Each property is translated to a Logix
    ``Type``.

    Supported:
        - primitives: integer, number, string, boolean, null
        - arrays with ``items`` (or without — permissive, item type Any)
        - nested objects
        - ``enum`` (single- or mixed-primitive)
        - ``anyOf`` (mapped to UnionType)
        - ``additionalProperties: true | false``

    Unsupported (raises ``ValueError``):
        - ``$ref``, ``$defs``, ``definitions``
        - ``oneOf``, ``allOf``, ``not``, ``if``/``then``/``else``
        - ``additionalProperties`` as a schema dict
        - ``patternProperties``
        - constraint keywords (``minimum``, ``maxLength``, ``pattern``, ...)

    The rationale: the proxy's job is to enforce *strong* validation
    before forwarding. Silently weakening a constraint to ``AnyType``
    would be the opposite. Better to fail at startup with a clear error
    and let the operator handle the specific tool.
    """
    if not isinstance(schema, dict):
        raise ValueError(
            f"MCP inputSchema must be a dict, got {type(schema).__name__}"
        )

    if schema.get("type") != "object":
        raise ValueError(
            f"MCP inputSchema must have type='object' at the top level; "
            f"got {schema.get('type')!r}"
        )

    _reject_unsupported(schema, path="$")

    properties = schema.get("properties") or {}
    required = frozenset(schema.get("required") or [])

    fields: dict[str, Type] = {}
    for name, prop_schema in properties.items():
        fields[name] = _prop_schema_to_type(prop_schema, path=f"$.{name}")

    # additionalProperties: absent (permissive per JSON Schema), True
    # (permissive), False (strict), or a schema dict (rejected above).
    additional = schema.get("additionalProperties", True) is not False

    return ObjectType(
        fields=fields,
        required=required,
        additional=additional,
    )


_UNSUPPORTED_KEYS = (
    "$ref", "$defs", "definitions",
    "oneOf", "allOf", "not", "if", "then", "else",
    "patternProperties",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern", "format",
    "minItems", "maxItems", "uniqueItems",
)


def _reject_unsupported(schema: dict[str, Any], *, path: str) -> None:
    for key in _UNSUPPORTED_KEYS:
        if key in schema:
            raise ValueError(
                f"MCP inputSchema uses unsupported keyword {key!r} at "
                f"{path}; this schema cannot be safely wrapped"
            )
    ap = schema.get("additionalProperties")
    if isinstance(ap, dict):
        raise ValueError(
            f"MCP inputSchema uses a schema for additionalProperties at "
            f"{path}; not supported in 0.1.0"
        )


def _prop_schema_to_type(schema: Any, *, path: str) -> Type:
    """Translate one property's JSON Schema into a Logix ``Type``."""
    if not isinstance(schema, dict):
        raise ValueError(
            f"property at {path} must be a schema dict, got "
            f"{type(schema).__name__}"
        )

    # enum -> LiteralType
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values:
            raise ValueError(f"enum at {path} must be a non-empty list")
        _reject_unsupported({k: v for k, v in schema.items() if k != "enum"}, path=path)
        return LiteralType(values=tuple(values))

    # anyOf -> UnionType
    if "anyOf" in schema:
        members = schema["anyOf"]
        if not isinstance(members, list) or not members:
            raise ValueError(f"anyOf at {path} must be a non-empty list")
        _reject_unsupported({k: v for k, v in schema.items() if k != "anyOf"}, path=path)
        return UnionType(
            members=tuple(_prop_schema_to_type(m, path=f"{path}.anyOf[{i}]")
                          for i, m in enumerate(members))
        )

    _reject_unsupported(schema, path=path)

    json_type = schema.get("type")
    if json_type is None:
        raise ValueError(
            f"property at {path} has no type; cannot map to a Logix Type"
        )

    if json_type == "integer":
        return IntType()
    if json_type == "number":
        return NumberType()
    if json_type == "string":
        return StrType()
    if json_type == "boolean":
        return BoolType()
    if json_type == "null":
        return NoneType()
    if json_type == "array":
        items = schema.get("items")
        if items is None:
            return ListType(item_type=AnyType())
        return ListType(item_type=_prop_schema_to_type(items, path=f"{path}[]"))
    if json_type == "object":
        properties = schema.get("properties") or {}
        required = frozenset(schema.get("required") or [])
        additional = schema.get("additionalProperties", True) is not False
        return ObjectType(
            fields={
                k: _prop_schema_to_type(v, path=f"{path}.{k}")
                for k, v in properties.items()
            },
            required=required,
            additional=additional,
        )

    raise ValueError(
        f"property at {path} has unsupported type {json_type!r}"
    )


# ---------------------------------------------------------------------------
# SchemaError -> Error helper (used by proxy startup validation)
# ---------------------------------------------------------------------------

def schema_errors_to_errors(
    schema_errors: list[SchemaError],
    *,
    code: str = "SCHEMA_VALIDATION_FAILED",
) -> list[Error]:
    """
    Convert ``SchemaError`` objects (from the schema engine) into the
    ``Error`` type that flows through the public API.
    """
    return [
        Error(code=code, message=se.message, path=se.path)
        for se in schema_errors
    ]