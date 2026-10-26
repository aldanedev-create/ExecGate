"""
End-to-end MCP wire-protocol tests.

Unlike ``test_server_tools_call.py`` (which calls ``_build_handler``
directly), this suite goes through the full MCP round-trip using
``fastmcp.Client(server.mcp)`` — the in-memory transport FastMCP 4.1.x
supports. It exercises:

- ``tools/list`` returning the right names, descriptions, and schemas
- ``tools/call`` returning success values
- ``tools/call`` returning error results for every failure mode Logiq
  can raise: ``UNKNOWN_CAPABILITY``, ``SCHEMA_VALIDATION_FAILED``,
  ``POLICY_REJECTED``, ``APPROVAL_REQUIRED``, ``HANDLER_FAILED``

Requires ``pytest-asyncio`` with ``asyncio_mode = "auto"`` (see
``pyproject.toml``) OR the ``@pytest.mark.asyncio`` markers below to be
honored. If async mode is disabled, these tests will be skipped with a
clear warning rather than silently passing.
"""

from __future__ import annotations

import asyncio

import pytest

from logiq import Deny, Logix
from logiq_mcp import LogixMCPServer

from .conftest import mcp_available


# If pytest-asyncio is not installed, skip the whole file with a clear
# message rather than error on unknown asyncio markers.
try:
    import pytest_asyncio  # noqa: F401
    HAS_PYTEST_ASYNCIO = True
except ImportError:
    HAS_PYTEST_ASYNCIO = False

pytestmark = [
    mcp_available,
    pytest.mark.skipif(
        not HAS_PYTEST_ASYNCIO,
        reason="wire-protocol tests require pytest-asyncio",
    ),
]


# ---------------------------------------------------------------------------
# Helper: build a server with a standard capability set
# ---------------------------------------------------------------------------

def _server_with_capabilities() -> tuple[LogixMCPServer, Logix]:
    logix = Logix()

    @logix.capability(effects="read")
    def add(a: int, b: int) -> int:
        "Add two integers."
        return a + b

    @logix.capability(effects="read")
    def get_order(order_id: int) -> dict[str, int]:
        "Retrieve an order."
        return {"id": order_id}

    @logix.capability(effects="write", requires_approval=True)
    def issue_refund(order_id: int, amount: float) -> dict[str, int]:
        "Issue a refund."
        return {"refunded": order_id}

    @logix.capability
    def crash(x: int) -> int:
        "Always crashes."
        raise ValueError("boom")

    return LogixMCPServer(logix, name="test"), logix


def _client(server: LogixMCPServer):
    from fastmcp import Client
    return Client(server.mcp)


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tools_list_returns_all_capabilities():
    server, _ = _server_with_capabilities()
    async with _client(server) as client:
        tools = await client.list_tools()

    names = {t.name for t in tools}
    assert names == {"add", "get_order", "issue_refund", "crash"}


@pytest.mark.asyncio
async def test_tools_list_descriptions():
    server, _ = _server_with_capabilities()
    async with _client(server) as client:
        tools = await client.list_tools()

    by_name = {t.name: t for t in tools}
    assert by_name["add"].description == "Add two integers."
    assert by_name["issue_refund"].description == "Issue a refund."


@pytest.mark.asyncio
async def test_tools_list_input_schemas():
    """The MCP advertisement must reflect the Logiq schema. FastMCP
    derives the schema from ``handler(**kwargs)`` unless the FastMCP
    version supports explicit schema registration. Verify whatever
    FastMCP actually exposes is usable."""
    server, _ = _server_with_capabilities()
    async with _client(server) as client:
        tools = await client.list_tools()

    by_name = {t.name: t for t in tools}
    add_schema = by_name["add"].inputSchema
    assert add_schema["type"] == "object"
    # Every FastMCP version we've seen surfaces at least the property keys.
    assert "properties" in add_schema or add_schema == {}


# ---------------------------------------------------------------------------
# tools/call: success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_add_returns_value():
    server, _ = _server_with_capabilities()
    async with _client(server) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})

    assert not result.is_error
    assert "5" in result.content[0].text


@pytest.mark.asyncio
async def test_call_get_order_returns_dict():
    server, _ = _server_with_capabilities()
    async with _client(server) as client:
        result = await client.call_tool("get_order", {"order_id": 502})

    assert not result.is_error
    text = result.content[0].text
    # Serialized dict contains the id.
    assert "502" in text


# ---------------------------------------------------------------------------
# tools/call: failures surface as MCP error results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_tool_rejected():
    server, _ = _server_with_capabilities()
    async with _client(server) as client:
        result = await client.call_tool(
            "does_not_exist", {}, raise_on_error=False,
        )

    assert result.is_error
    assert "UNKNOWN_CAPABILITY" in result.content[0].text


@pytest.mark.asyncio
async def test_wrong_type_rejected():
    server, _ = _server_with_capabilities()
    async with _client(server) as client:
        result = await client.call_tool(
            "add", {"a": "not-an-int", "b": 3}, raise_on_error=False,
        )

    assert result.is_error
    assert "SCHEMA_VALIDATION_FAILED" in result.content[0].text


@pytest.mark.asyncio
async def test_extra_arg_rejected():
    server, _ = _server_with_capabilities()
    async with _client(server) as client:
        result = await client.call_tool(
            "add", {"a": 1, "b": 2, "c": 3}, raise_on_error=False,
        )

    assert result.is_error
    assert "SCHEMA_VALIDATION_FAILED" in result.content[0].text


@pytest.mark.asyncio
async def test_handler_exception_rejected():
    server, _ = _server_with_capabilities()
    async with _client(server) as client:
        result = await client.call_tool("crash", {"x": 1}, raise_on_error=False)

    assert result.is_error
    assert "HANDLER_FAILED" in result.content[0].text


@pytest.mark.asyncio
async def test_approval_required_rejected():
    server, _ = _server_with_capabilities()
    async with _client(server) as client:
        result = await client.call_tool(
            "issue_refund",
            {"order_id": 1, "amount": 5.0},
            raise_on_error=False,
        )

    assert result.is_error
    assert "APPROVAL_REQUIRED" in result.content[0].text


@pytest.mark.asyncio
async def test_invariant_deny_rejected():
    server, logix = _server_with_capabilities()
    logix.authorize(
        "get_order",
        check=lambda args, ctx: Deny("BLOCKED", "not today"),
    )

    async with _client(server) as client:
        result = await client.call_tool(
            "get_order", {"order_id": 1}, raise_on_error=False,
        )

    assert result.is_error
    assert "POLICY_REJECTED" in result.content[0].text


# ---------------------------------------------------------------------------
# Failures do not invoke handlers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_tool_does_not_invoke_handler():
    logix = Logix()
    invoked: list[int] = []

    @logix.capability
    def add(a: int, b: int) -> int:
        invoked.append(1)
        return a + b

    server = LogixMCPServer(logix, name="test")
    async with _client(server) as client:
        await client.call_tool("does_not_exist", {}, raise_on_error=False)

    assert invoked == []


@pytest.mark.asyncio
async def test_schema_failure_does_not_invoke_handler():
    logix = Logix()
    invoked: list[int] = []

    @logix.capability
    def add(a: int, b: int) -> int:
        invoked.append(1)
        return a + b

    server = LogixMCPServer(logix, name="test")
    async with _client(server) as client:
        await client.call_tool(
            "add", {"a": "wrong", "b": 1}, raise_on_error=False,
        )

    assert invoked == []


# ---------------------------------------------------------------------------
# context_factory flows through the wire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_factory_sets_principal():
    """The principal provided by context_factory is what invariants see."""
    logix = Logix()
    captured: list[str] = []

    @logix.capability
    def op(x: int) -> int:
        return x

    def capture(args, ctx):
        captured.append(ctx.principal)
        from logiq import Allow
        return Allow()

    logix.authorize("op", check=capture)
    server = LogixMCPServer(
        logix, name="test",
        context_factory=lambda: logix.context(principal="alice"),
    )

    async with _client(server) as client:
        await client.call_tool("op", {"x": 1})

    assert captured == ["alice"]