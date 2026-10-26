"""
Server exposure: the catalog.

``LogixMCPServer.describe()`` returns the ``tools/list`` payload as plain
dicts. It reads from ``logix.tools.describe()`` directly — bypassing
FastMCP — so it works without a live MCP transport and always reflects
the strict schema.
"""

from __future__ import annotations

from logiq import Logix
from logiq_mcp.server import LogixMCPServer

from .mcp_support import mcp_available


@mcp_available
def test_describe_empty_engine():
    logix = Logix()
    server = LogixMCPServer(logix, name="test")
    assert server.describe() == []


@mcp_available
def test_describe_one_capability():
    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        "Add two integers."
        return a + b

    server = LogixMCPServer(logix, name="test")
    tools = server.describe()
    assert len(tools) == 1
    assert tools[0]["name"] == "add"
    assert tools[0]["description"] == "Add two integers."
    assert tools[0]["inputSchema"]["type"] == "object"
    assert tools[0]["inputSchema"]["properties"]["a"] == {"type": "integer"}
    assert tools[0]["inputSchema"]["required"] == ["a", "b"]
    assert tools[0]["inputSchema"]["additionalProperties"] is False


@mcp_available
def test_describe_multiple_capabilities_preserves_order():
    logix = Logix()

    @logix.capability
    def a() -> int:
        return 1

    @logix.capability
    def b() -> int:
        return 2

    @logix.capability
    def c() -> int:
        return 3

    server = LogixMCPServer(logix, name="test")
    names = [t["name"] for t in server.describe()]
    assert names == ["a", "b", "c"]


@mcp_available
def test_describe_schema_matches_logix_catalog():
    """The MCP catalog and the Logix catalog share the same schema —
    same one-schema-two-uses guarantee."""
    logix = Logix()

    @logix.capability
    def get_order(order_id: int) -> dict[str, int]:
        return {"id": order_id}

    server = LogixMCPServer(logix, name="test")

    mcp_tool = server.describe()[0]
    logix_spec = logix.tools.describe()[0]

    assert mcp_tool["name"] == logix_spec.name
    assert mcp_tool["inputSchema"] == logix_spec.input_schema


@mcp_available
def test_describe_reflects_effects_and_approval():
    """The MCP description does not currently carry effects/approval —
    those are Logix-side metadata. This test documents what MCP clients
    actually receive."""
    logix = Logix()

    @logix.capability(effects="write", requires_approval=True)
    def refund(order_id: int) -> dict[str, int]:
        return {"ok": 1}

    server = LogixMCPServer(logix, name="test")
    tool = server.describe()[0]

    # MCP tools/list has only name + description + inputSchema. Effects
    # and approval are advertised by Logix to Logix-aware clients, not
    # surfaced in the standard MCP shape.
    assert set(tool.keys()) == {"name", "description", "inputSchema"}


@mcp_available
def test_describe_json_serializable():
    """The tools/list payload must be JSON-serializable — it crosses the
    wire."""
    import json

    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    server = LogixMCPServer(logix, name="test")
    json.dumps(server.describe())  # must not raise


@mcp_available
def test_mcp_property_returns_fastmcp_instance():
    """The underlying FastMCP instance is exposed for advanced use."""
    from fastmcp import FastMCP

    logix = Logix()
    server = LogixMCPServer(logix, name="test")
    assert isinstance(server.mcp, FastMCP)
