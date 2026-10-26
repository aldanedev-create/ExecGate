"""
The AI catalog.

``logix.tools.describe()`` and ``logix.tools.format(provider)`` expose the
capabilities to an AI. The load-bearing property: the catalog and the
verifier use **the same schema** — they cannot disagree. A well-behaved
client that reads the catalog and produces a schema-conformant plan will
pass verification; the two layers are structurally coupled.

These tests exercise wiring, not provider-specific wire formats (that's
``tests/adapters/``'s job).
"""

from __future__ import annotations

import json

import pytest

from execgate import ToolSpec

# ---------------------------------------------------------------------------
# describe() — neutral catalog
# ---------------------------------------------------------------------------


def test_describe_returns_tool_specs(logix):
    @logix.capability
    def add(a: int, b: int) -> int:
        "Add two integers."
        return a + b

    specs = logix.tools.describe()
    assert len(specs) == 1
    assert isinstance(specs[0], ToolSpec)


def test_describe_includes_all_fields(logix):
    @logix.capability(effects="write", requires_approval=True)
    def refund(order_id: int, amount: float) -> dict[str, int]:
        "Issue a refund."
        return {"ok": 1}

    spec = logix.tools.describe()[0]
    assert spec.name == "refund"
    assert spec.description == "Issue a refund."
    assert spec.input_schema["type"] == "object"
    assert spec.input_schema["properties"]["order_id"] == {"type": "integer"}
    assert spec.input_schema["properties"]["amount"] == {"type": "number"}
    # ``required`` is emitted sorted so the catalog and snapshot hash are
    # deterministic (ObjectType.required is an unordered frozenset).
    assert spec.input_schema["required"] == ["amount", "order_id"]
    assert spec.input_schema["additionalProperties"] is False
    assert spec.effects == "write"
    assert spec.approval == "required"
    assert spec.schema_version == "1"


def test_describe_no_approval_yields_none(logix):
    @logix.capability
    def read(x: int) -> int:
        return x

    assert logix.tools.describe()[0].approval is None


def test_describe_no_effects_yields_none(logix):
    @logix.capability
    def read(x: int) -> int:
        return x

    assert logix.tools.describe()[0].effects is None


def test_describe_preserves_registration_order(logix):
    @logix.capability
    def a() -> int:
        return 1

    @logix.capability
    def b() -> int:
        return 2

    @logix.capability
    def c() -> int:
        return 3

    names = [s.name for s in logix.tools.describe()]
    assert names == ["a", "b", "c"]


def test_describe_empty_engine(logix):
    assert logix.tools.describe() == []


# ---------------------------------------------------------------------------
# Same schema, two uses — the load-bearing property
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("capability_name", ["add", "refund", "noop"])
def test_catalog_schema_matches_verifier_schema(logix, capability_name):
    """The schema the catalog advertises must be byte-identical to the
    schema the verifier validates against. If they ever diverge, a client
    that reads the catalog could produce plans the verifier rejects —
    exactly the coupling ``docs/system-design.md §10`` promises."""

    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    @logix.capability
    def refund(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    @logix.capability
    def noop() -> None:
        return None

    catalog_schema = logix.tools.for_capability(capability_name).input_schema
    verifier_schema = logix.schemas.for_capability(capability_name).input
    assert catalog_schema == verifier_schema


def test_catalog_schema_advertises_what_verifier_enforces(logix):
    """Advertise a schema, then violate it — the same schema, used by the
    verifier, must reject the plan before any handler runs."""
    invoked: list[int] = []

    @logix.capability
    def bounded(x: int) -> int:
        invoked.append(x)
        return x

    catalog = logix.tools.for_capability("bounded").input_schema
    # The catalog says x is a required integer.
    assert catalog["properties"]["x"] == {"type": "integer"}
    assert "x" in catalog["required"]

    result = logix.run({"call": "bounded", "with": {"x": "not-an-int"}})
    assert not result.ok
    assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"
    assert invoked == []


# ---------------------------------------------------------------------------
# format() — wiring to adapters
# ---------------------------------------------------------------------------


def test_format_json_returns_neutral_dicts(logix):
    @logix.capability
    def add(a: int, b: int) -> int:
        "Add."
        return a + b

    result = logix.tools.format("json")
    assert isinstance(result, list)
    assert result[0]["name"] == "add"
    assert result[0]["input_schema"]["type"] == "object"
    # JSON-serializable — the AI client must be able to send it.
    json.dumps(result)


def test_format_json_equals_describe_neutral(logix):
    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    neutral = [spec.to_neutral_dict() for spec in logix.tools.describe()]
    assert logix.tools.format("json") == neutral


def test_format_unknown_provider_falls_back_to_neutral(logix):
    """The core promise: unknown provider name never raises."""

    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    result = logix.tools.format("some-unregistered-provider")
    assert isinstance(result, list)
    assert result[0]["name"] == "add"
    assert "input_schema" in result[0]


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini", "local"])
def test_format_known_provider_succeeds(logix, provider):
    """If execgate_ai is installed (it is, per dev extras), every registered
    provider name resolves to a working adapter."""

    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    result = logix.tools.format(provider)
    # Serialization proves it's a wire-ready catalog, not a live object.
    json.dumps(result, default=str)


def test_format_openai_produces_function_tools(logix):
    @logix.capability
    def add(a: int, b: int) -> int:
        "Add."
        return a + b

    tools = logix.tools.format("openai")
    assert isinstance(tools, list)
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "add"
    assert tools[0]["function"]["parameters"]["type"] == "object"


# ---------------------------------------------------------------------------
# for_capability()
# ---------------------------------------------------------------------------


def test_for_capability_returns_spec(logix):
    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    spec = logix.tools.for_capability("add")
    assert isinstance(spec, ToolSpec)
    assert spec.name == "add"


def test_for_capability_unknown_raises(logix):
    with pytest.raises(KeyError):
        logix.tools.for_capability("does_not_exist")


# ---------------------------------------------------------------------------
# names()
# ---------------------------------------------------------------------------


def test_tools_names(logix):
    @logix.capability
    def a() -> int:
        return 1

    @logix.capability
    def b() -> int:
        return 2

    assert logix.tools.names() == ["a", "b"]


# ---------------------------------------------------------------------------
# Consistency across describe() and for_capability()
# ---------------------------------------------------------------------------


def test_describe_and_for_capability_agree(logix):
    @logix.capability(effects="read")
    def add(a: int, b: int) -> int:
        "Add."
        return a + b

    describe_spec = logix.tools.describe()[0]
    for_spec = logix.tools.for_capability("add")
    assert describe_spec == for_spec
