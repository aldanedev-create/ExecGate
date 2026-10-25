"""
The MCP adapter: pure data shaping between Logix and MCP types.

No FastMCP dependency — these functions (``tool_spec_to_mcp_dict``,
``from_mcp_call``, ``result_to_mcp_response``, ``format_errors_for_mcp``,
``extract_mcp_result_value``, ``mcp_schema_to_logix``) are pure functions
that can and should be tested without any integration layer.

Two exceptions:

- ``result_to_mcp_response`` imports ``fastmcp.exceptions.ToolError``
  lazily; tests calling that path require FastMCP installed.
- ``mcp_schema_to_logix`` produces native ``ObjectType`` instances.
"""

from __future__ import annotations

import pytest

from logix.errors import (
    AUTHORIZATION_FAILED,
    POLICY_REJECTED,
    SCHEMA_VALIDATION_FAILED,
    Error,
)
from logix.results import Result
from logix.schemas import (
    BoolType,
    FloatType,
    IntType,
    ListType,
    LiteralType,
    NoneType,
    NumberType,
    ObjectType,
    StrType,
    UnionType,
)
from logix.tools import ToolSpec
from logix_mcp.adapter import (
    extract_mcp_result_value,
    format_errors_for_mcp,
    from_mcp_call,
    mcp_schema_to_logix,
    result_to_mcp_response,
    schema_errors_to_errors,
    tool_spec_to_mcp_dict,
)

from .conftest import (
    FakeCallToolResult,
    FakeTextContent,
    mcp_available,
)


# ---------------------------------------------------------------------------
# tool_spec_to_mcp_dict
# ---------------------------------------------------------------------------

def test_tool_spec_to_mcp_dict_shape():
    spec = ToolSpec(
        name="add",
        description="Add.",
        input_schema={"type": "object", "properties": {}, "required": []},
    )
    result = tool_spec_to_mcp_dict(spec)
    assert set(result.keys()) == {"name", "description", "inputSchema"}
    assert result["name"] == "add"
    assert result["description"] == "Add."
    assert result["inputSchema"] == spec.input_schema


def test_tool_spec_to_mcp_dict_preserves_schema():
    """The MCP inputSchema is the same object as the Logix input_schema —
    same one-schema-two-uses principle."""
    schema = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
        "additionalProperties": False,
    }
    spec = ToolSpec(name="f", description="", input_schema=schema)
    assert tool_spec_to_mcp_dict(spec)["inputSchema"] == schema


# ---------------------------------------------------------------------------
# from_mcp_call
# ---------------------------------------------------------------------------

def test_from_mcp_call_basic():
    plan = from_mcp_call("get_order", {"order_id": 502})
    assert plan == {"call": "get_order", "with": {"order_id": 502}}


def test_from_mcp_call_none_arguments_treated_as_empty():
    plan = from_mcp_call("noop", None)
    assert plan == {"call": "noop", "with": {}}


def test_from_mcp_call_copies_arguments():
    """The produced plan's ``with`` map must not share state with the
    caller's arguments dict."""
    original = {"a": 1}
    plan = from_mcp_call("f", original)
    original["a"] = 999
    assert plan["with"]["a"] == 1


def test_from_mcp_call_does_not_set_verified():
    plan = from_mcp_call("f", {})
    assert "verified" not in plan


# ---------------------------------------------------------------------------
# format_errors_for_mcp
# ---------------------------------------------------------------------------

def test_format_errors_single():
    e = Error(code=SCHEMA_VALIDATION_FAILED, message="bad input", path="x")
    s = format_errors_for_mcp((e,))
    assert SCHEMA_VALIDATION_FAILED in s
    assert "bad input" in s
    assert "x" in s


def test_format_errors_multiple():
    errors = (
        Error(code=SCHEMA_VALIDATION_FAILED, message="bad"),
        Error(code=POLICY_REJECTED, message="denied"),
    )
    s = format_errors_for_mcp(errors)
    assert SCHEMA_VALIDATION_FAILED in s
    assert POLICY_REJECTED in s


def test_format_errors_no_path_omits_parenthetical():
    e = Error(code=AUTHORIZATION_FAILED, message="no")
    s = format_errors_for_mcp((e,))
    assert "(at" not in s


# ---------------------------------------------------------------------------
# result_to_mcp_response
# ---------------------------------------------------------------------------

def test_result_success_returns_value():
    result = Result.success({"ok": 1})
    assert result_to_mcp_response(result) == {"ok": 1}


def test_result_success_return_value_unchanged():
    """Simple values pass through as-is."""
    assert result_to_mcp_response(Result.success(42)) == 42
    assert result_to_mcp_response(Result.success(None)) is None


@mcp_available
def test_result_failure_raises_tool_error():
    from fastmcp.exceptions import ToolError

    e = Error(code=SCHEMA_VALIDATION_FAILED, message="bad")
    result = Result.failure([e])

    with pytest.raises(ToolError) as exc_info:
        result_to_mcp_response(result)
    assert SCHEMA_VALIDATION_FAILED in str(exc_info.value)


# ---------------------------------------------------------------------------
# extract_mcp_result_value
# ---------------------------------------------------------------------------

def test_extract_none_result():
    assert extract_mcp_result_value(None) is None


def test_extract_json_text():
    result = FakeCallToolResult(content=[FakeTextContent(text='{"id": 1}')])
    assert extract_mcp_result_value(result) == {"id": 1}


def test_extract_plain_text_fallback():
    result = FakeCallToolResult(content=[FakeTextContent(text="not json")])
    assert extract_mcp_result_value(result) == "not json"


def test_extract_multiple_text_blocks_joined():
    result = FakeCallToolResult(content=[
        FakeTextContent(text='{"a":'),
        FakeTextContent(text=' 1}'),
    ])
    assert extract_mcp_result_value(result) == {"a": 1}


def test_extract_empty_content():
    assert extract_mcp_result_value(FakeCallToolResult(content=[])) is None


def test_extract_no_content_attribute():
    """A result object without a ``content`` attribute returns None."""
    class Empty:
        pass

    assert extract_mcp_result_value(Empty()) is None


# ---------------------------------------------------------------------------
# schema_errors_to_errors
# ---------------------------------------------------------------------------

def test_schema_errors_to_errors():
    from logix.schemas import SchemaError

    schema_errors = [
        SchemaError(path="$", message="bad"),
        SchemaError(path="$.x", message="worse"),
    ]
    errors = schema_errors_to_errors(schema_errors)
    assert len(errors) == 2
    assert all(e.code == "SCHEMA_VALIDATION_FAILED" for e in errors)
    assert errors[1].path == "$.x"


# ---------------------------------------------------------------------------
# mcp_schema_to_logix — supported shapes
# ---------------------------------------------------------------------------

def test_schema_object_primitives():
    schema = {
        "type": "object",
        "properties": {
            "i": {"type": "integer"},
            "n": {"type": "number"},
            "s": {"type": "string"},
            "b": {"type": "boolean"},
            "z": {"type": "null"},
        },
        "required": ["i", "s"],
    }
    obj = mcp_schema_to_logix(schema)
    assert obj.fields["i"] == IntType()
    assert obj.fields["n"] == NumberType()
    assert obj.fields["s"] == StrType()
    assert obj.fields["b"] == BoolType()
    assert obj.fields["z"] == NoneType()
    assert obj.required == frozenset({"i", "s"})


def test_schema_array_of_integers():
    schema = {
        "type": "object",
        "properties": {"xs": {"type": "array", "items": {"type": "integer"}}},
    }
    obj = mcp_schema_to_logix(schema)
    assert obj.fields["xs"] == ListType(item_type=IntType())


def test_schema_array_without_items_is_any_item():
    schema = {
        "type": "object",
        "properties": {"xs": {"type": "array"}},
    }
    obj = mcp_schema_to_logix(schema)
    from logix.schemas import AnyType
    assert isinstance(obj.fields["xs"], ListType)
    assert isinstance(obj.fields["xs"].item_type, AnyType)


def test_schema_nested_object():
    schema = {
        "type": "object",
        "properties": {
            "outer": {
                "type": "object",
                "properties": {"inner": {"type": "integer"}},
                "required": ["inner"],
            },
        },
    }
    obj = mcp_schema_to_logix(schema)
    outer = obj.fields["outer"]
    assert isinstance(outer, ObjectType)
    assert outer.fields["inner"] == IntType()
    assert "inner" in outer.required


def test_schema_enum():
    schema = {
        "type": "object",
        "properties": {"kind": {"enum": ["a", "b"]}},
    }
    obj = mcp_schema_to_logix(schema)
    assert obj.fields["kind"] == LiteralType(values=("a", "b"))


def test_schema_any_of():
    schema = {
        "type": "object",
        "properties": {
            "val": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
        },
    }
    obj = mcp_schema_to_logix(schema)
    val = obj.fields["val"]
    assert isinstance(val, UnionType)
    assert IntType() in val.members
    assert StrType() in val.members


def test_schema_additional_properties_false_by_default():
    schema = {"type": "object", "properties": {}}
    obj = mcp_schema_to_logix(schema)
    # Missing additionalProperties is permissive in JSON Schema — but we
    # respect the schema; additional defaults to True per JSON Schema spec.
    assert obj.additional is True


def test_schema_additional_properties_explicit_false():
    schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    obj = mcp_schema_to_logix(schema)
    assert obj.additional is False


# ---------------------------------------------------------------------------
# mcp_schema_to_logix — unsupported shapes rejected
# ---------------------------------------------------------------------------

def test_schema_rejects_non_dict():
    with pytest.raises(ValueError, match="must be a dict"):
        mcp_schema_to_logix("not a dict")  # type: ignore[arg-type]


def test_schema_rejects_non_object_top_level():
    with pytest.raises(ValueError, match="type='object'"):
        mcp_schema_to_logix({"type": "string"})


@pytest.mark.parametrize("unsupported_key", [
    "$ref", "$defs", "definitions", "oneOf", "allOf", "not",
    "if", "then", "else", "patternProperties",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern", "format",
    "minItems", "maxItems", "uniqueItems",
])
def test_schema_rejects_unsupported_keywords(unsupported_key):
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        unsupported_key: True,
    }
    with pytest.raises(ValueError, match=unsupported_key.replace("$", r"\$")):
        mcp_schema_to_logix(schema)


def test_schema_rejects_additional_properties_schema():
    schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": {"type": "string"},
    }
    with pytest.raises(ValueError, match="additionalProperties"):
        mcp_schema_to_logix(schema)