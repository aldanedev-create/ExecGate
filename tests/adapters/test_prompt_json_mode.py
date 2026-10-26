"""
JSON-mode prompt builder.

``prompt_json_mode.build(specs)`` produces a system-prompt string that
describes the available capabilities and instructs the model to respond
with a single ``{"call": ..., "with": ...}`` JSON object.

Tests verify structural properties of the prompt — the presence of every
capability, the embedded JSON Schema, the instruction variant (strict vs
lenient), and the optional system prefix. They do not (and cannot)
verify that a model will obey it.
"""

from __future__ import annotations

import json

import pytest

from logiq.tools import ToolSpec
from logiq_ai.prompt_json_mode import build

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="get_order",
            description="Retrieve an order by its ID.",
            input_schema={
                "type": "object",
                "properties": {"order_id": {"type": "integer"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            effects="read",
        ),
        ToolSpec(
            name="issue_refund",
            description="Issue a refund.",
            input_schema={
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer"},
                    "amount": {"type": "number"},
                },
                "required": ["order_id", "amount"],
                "additionalProperties": False,
            },
            effects="write",
            approval="principal_bound",
        ),
    ]


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------


def test_build_returns_string(sample_specs):
    prompt = build(sample_specs)
    assert isinstance(prompt, str)
    assert prompt  # non-empty


def test_build_empty_catalog():
    """Empty catalog still produces a valid prompt — with an explicit
    '(none registered)' marker rather than a broken list."""
    prompt = build([])
    assert isinstance(prompt, str)
    assert "(none registered)" in prompt


def test_build_has_capabilities_header(sample_specs):
    prompt = build(sample_specs)
    assert "# Available capabilities" in prompt


# ---------------------------------------------------------------------------
# Every capability appears with its schema
# ---------------------------------------------------------------------------


def test_build_includes_every_capability_name(sample_specs):
    prompt = build(sample_specs)
    for spec in sample_specs:
        assert spec.name in prompt, f"capability {spec.name!r} missing from prompt"


def test_build_includes_every_description(sample_specs):
    prompt = build(sample_specs)
    for spec in sample_specs:
        assert spec.description in prompt


def test_build_includes_every_input_schema(sample_specs):
    """The JSON Schema must be embedded so the model can see argument
    types, required fields, and constraints."""
    prompt = build(sample_specs)
    for spec in sample_specs:
        # Every property name appears in the prompt.
        for prop in spec.input_schema.get("properties", {}):
            assert prop in prompt, f"argument {prop!r} of {spec.name!r} missing from prompt"


def test_build_includes_required_fields(sample_specs):
    prompt = build(sample_specs)
    # Both specs require "order_id".
    assert prompt.count("order_id") >= 2


def test_build_includes_output_schema_when_present(sample_specs):
    prompt = build(sample_specs)
    # get_order has an output_schema; it should be embedded.
    assert "Output schema" in prompt


def test_build_omits_output_schema_when_absent():
    spec = ToolSpec(
        name="noop",
        description="Does nothing.",
        input_schema={"type": "object", "properties": {}},
        output_schema=None,
    )
    prompt = build([spec])
    assert "noop" in prompt
    # No output schema heading for a spec that has none.
    assert "Output schema" not in prompt


# ---------------------------------------------------------------------------
# Effects and approval metadata
# ---------------------------------------------------------------------------


def test_build_includes_effects(sample_specs):
    prompt = build(sample_specs)
    assert "_effects: read_" in prompt
    assert "_effects: write_" in prompt


def test_build_includes_approval(sample_specs):
    prompt = build(sample_specs)
    assert "_approval: principal_bound_" in prompt


def test_build_omits_effects_when_none():
    spec = ToolSpec(
        name="x",
        description="",
        input_schema={"type": "object", "properties": {}},
        effects=None,
    )
    prompt = build([spec])
    assert "_effects:" not in prompt


def test_build_omits_approval_when_none():
    spec = ToolSpec(
        name="x",
        description="",
        input_schema={"type": "object", "properties": {}},
        approval=None,
    )
    prompt = build([spec])
    assert "_approval:" not in prompt


# ---------------------------------------------------------------------------
# Instruction variant: strict vs lenient
# ---------------------------------------------------------------------------


def test_build_default_is_strict(sample_specs):
    prompt = build(sample_specs)
    # The strict instructions include the "__no_op__" escape hatch.
    assert "__no_op__" in prompt
    # And the "no prose" language.
    assert "no prose" in prompt.lower() or "exactly one JSON" in prompt


def test_build_lenient_omits_no_op(sample_specs):
    prompt = build(sample_specs, strict=False)
    # The lenient instructions do not mention __no_op__.
    assert "__no_op__" not in prompt
    # And use "somewhere in your response" language.
    assert "somewhere" in prompt.lower()


def test_build_both_variants_require_call_shape(sample_specs):
    strict = build(sample_specs, strict=True)
    lenient = build(sample_specs, strict=False)
    for prompt in (strict, lenient):
        assert '"call"' in prompt or "call" in prompt
        assert '"with"' in prompt or "with" in prompt


# ---------------------------------------------------------------------------
# System prefix
# ---------------------------------------------------------------------------


def test_build_prepends_system_text(sample_specs):
    prompt = build(sample_specs, system="You are a support agent.")
    assert prompt.startswith("You are a support agent.")
    # Capabilities still present after the prefix.
    assert "# Available capabilities" in prompt


def test_build_no_system_does_not_add_prefix(sample_specs):
    prompt = build(sample_specs)
    assert prompt.startswith("# Available capabilities")


def test_build_system_is_stripped(sample_specs):
    prompt = build(sample_specs, system="  \n  You are helpful.  \n  ")
    assert prompt.startswith("You are helpful.")
    assert prompt.count("You are helpful.") == 1


def test_build_empty_system_no_prefix(sample_specs):
    """Empty or whitespace-only system string is not prepended."""
    prompt = build(sample_specs, system="   ")
    assert prompt.startswith("# Available capabilities")


# ---------------------------------------------------------------------------
# JSON Schema embedding is valid JSON
# ---------------------------------------------------------------------------


def test_build_embeds_valid_json_schema_blocks(sample_specs):
    """Every ```json ... ``` fenced block must be valid JSON. This proves
    the schema is machine-readable, not just present as a string."""
    prompt = build(sample_specs)
    blocks = _extract_json_blocks(prompt)
    assert blocks, "no fenced JSON blocks in prompt"
    for block in blocks:
        # Should parse without error.
        json.loads(block)


def test_build_input_schema_round_trips(sample_specs):
    """The input schema embedded in the prompt is byte-identical to the
    ToolSpec's schema (after JSON round-trip)."""
    prompt = build(sample_specs)
    blocks = _extract_json_blocks(prompt)

    expected_schemas = [spec.input_schema for spec in sample_specs]
    parsed = [json.loads(b) for b in blocks]

    for schema in expected_schemas:
        assert any(p == schema for p in parsed), (
            f"input schema {schema} not found in embedded blocks"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_json_blocks(prompt: str) -> list[str]:
    """Extract content between ```json and ``` markers."""
    blocks: list[str] = []
    in_block = False
    current: list[str] = []
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped == "```json":
            in_block = True
            current = []
        elif stripped == "```" and in_block:
            in_block = False
            blocks.append("\n".join(current))
        elif in_block:
            current.append(line)
    return blocks
