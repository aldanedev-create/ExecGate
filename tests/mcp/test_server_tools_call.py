"""
Server tool invocation.

The handler FastMCP registers for each capability is the one produced by
``LogixMCPServer._build_handler(name)``. That handler is what a live
MCP client's ``tools/call`` request runs. We test it directly — portable
across FastMCP versions, and the source of truth for the call path.

End-to-end through FastMCP's wire protocol is exercised by manual
integration (see ``examples/09_mcp_server_quickstart.py``).
"""

from __future__ import annotations

import asyncio

import pytest

from logix import Deny, Logix
from logix_mcp.server import LogixMCPServer

from .conftest import mcp_available


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

@mcp_available
def test_handler_returns_value_on_success():
    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    server = LogixMCPServer(logix, name="test")
    handler = server._build_handler("add")

    result = asyncio.run(handler(a=3, b=4))
    assert result == 7


@mcp_available
def test_handler_returns_dict_value():
    logix = Logix()

    @logix.capability
    def get_order(order_id: int) -> dict[str, int]:
        return {"id": order_id, "status": 1}

    server = LogixMCPServer(logix, name="test")
    handler = server._build_handler("get_order")

    result = asyncio.run(handler(order_id=502))
    assert result == {"id": 502, "status": 1}


@mcp_available
def test_handler_returns_none():
    logix = Logix()

    @logix.capability
    def noop(x: int) -> None:
        return None

    server = LogixMCPServer(logix, name="test")
    handler = server._build_handler("noop")

    result = asyncio.run(handler(x=1))
    assert result is None


# ---------------------------------------------------------------------------
# Failure path — ToolError
# ---------------------------------------------------------------------------

@mcp_available
def test_handler_raises_on_schema_failure():
    from fastmcp.exceptions import ToolError

    invoked: list[int] = []

    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        invoked.append(1)
        return a + b

    server = LogixMCPServer(logix, name="test")
    handler = server._build_handler("add")

    with pytest.raises(ToolError) as exc_info:
        asyncio.run(handler(a="not-an-int", b=4))

    assert "SCHEMA_VALIDATION_FAILED" in str(exc_info.value)
    assert invoked == []  # handler never ran


@mcp_available
def test_handler_raises_on_invariant_deny():
    from fastmcp.exceptions import ToolError

    invoked: list[int] = []

    logix = Logix()

    @logix.capability
    def refund(order_id: int) -> dict[str, int]:
        invoked.append(1)
        return {"ok": 1}

    logix.authorize(refund, check=lambda args, ctx: Deny("BLOCKED", "no"))
    server = LogixMCPServer(logix, name="test")
    handler = server._build_handler("refund")

    with pytest.raises(ToolError) as exc_info:
        asyncio.run(handler(order_id=1))

    assert "POLICY_REJECTED" in str(exc_info.value)
    assert invoked == []


@mcp_available
def test_handler_raises_on_approval_required():
    from fastmcp.exceptions import ToolError

    invoked: list[int] = []

    logix = Logix()

    @logix.capability
    def refund(order_id: int) -> dict[str, int]:
        invoked.append(1)
        return {"ok": 1}

    logix.require_approval(refund)
    server = LogixMCPServer(logix, name="test")
    handler = server._build_handler("refund")

    with pytest.raises(ToolError) as exc_info:
        asyncio.run(handler(order_id=1))

    assert "APPROVAL_REQUIRED" in str(exc_info.value)
    assert invoked == []


@mcp_available
def test_handler_raises_on_handler_exception():
    from fastmcp.exceptions import ToolError

    logix = Logix()

    @logix.capability
    def fail(x: int) -> int:
        raise ValueError("boom")

    server = LogixMCPServer(logix, name="test")
    handler = server._build_handler("fail")

    with pytest.raises(ToolError) as exc_info:
        asyncio.run(handler(x=1))

    assert "HANDLER_FAILED" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Handler naming
# ---------------------------------------------------------------------------

@mcp_available
def test_handler_name_is_capability_name():
    """FastMCP reads ``handler.__name__`` for tool dispatch; it must be
    the capability name, not a decorated variant."""
    logix = Logix()

    @logix.capability
    def get_order(order_id: int) -> dict[str, int]:
        return {"id": order_id}

    server = LogixMCPServer(logix, name="test")
    handler = server._build_handler("get_order")
    assert handler.__name__ == "get_order"


# ---------------------------------------------------------------------------
# Context factory
# ---------------------------------------------------------------------------

@mcp_available
def test_context_factory_is_called_per_invocation():
    """The context factory runs once per handler call — not once at
    server construction."""
    factory_calls: list[int] = []

    def factory():
        factory_calls.append(1)
        return Logix().context(principal="alice")

    logix = Logix()

    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    server = LogixMCPServer(logix, name="test", context_factory=factory)
    handler = server._build_handler("add")

    asyncio.run(handler(a=1, b=2))
    asyncio.run(handler(a=3, b=4))

    assert len(factory_calls) == 2


@mcp_available
def test_context_factory_sees_principal():
    """The context the handler receives uses the factory's output."""
    from logix.context import ExecutionContext

    captured: list[ExecutionContext] = []

    def factory():
        ctx = ExecutionContext(principal="alice")
        captured.append(ctx)
        return ctx

    logix = Logix()

    @logix.capability
    def op(x: int) -> int:
        return x

    def capture_ctx(args, ctx):
        captured.append(ctx)
        from logix import Allow
        return Allow()

    logix.authorize(op, check=capture_ctx)
    server = LogixMCPServer(logix, name="test", context_factory=factory)
    handler = server._build_handler("op")

    asyncio.run(handler(x=1))

    # Both factory and invariant captured contexts; all should be alice.
    principals = [c.principal for c in captured]
    assert "alice" in principals