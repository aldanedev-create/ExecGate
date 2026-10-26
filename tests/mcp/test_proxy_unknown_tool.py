"""
Proxy: unknown capabilities never forward.

The proxy's registry is the source of truth. A tool name not in the
registry — invented by the client, or an upstream tool that was never
fetched — is rejected with ``UNKNOWN_CAPABILITY`` before the upstream
client sees the call.

Also tests startup and shutdown lifecycle.
"""

from __future__ import annotations

import asyncio

import pytest

from logiq import Logix
from logiq_mcp.proxy import LogixMCPProxy

from mcp_support import FakeMCPClient, mcp_available


@mcp_available
def test_unknown_tool_rejected_before_forwarding(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            result = await asyncio.to_thread(
                logix.run,
                {"call": "unknown_tool", "with": {}},
            )
            assert not result.ok
            assert result.errors[0].code == "UNKNOWN_CAPABILITY"
            assert client.calls == [], "upstream was called for unknown tool"
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_registered_upstream_tool_forwards(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            # Known capability: forwarded to upstream.
            result = await asyncio.to_thread(
                logix.run,
                {"call": "upstream_get_order", "with": {"order_id": 502}},
            )
            assert result.ok, result.errors
            assert client.calls == [("upstream_get_order", {"order_id": 502})]
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_lookalike_name_rejected(fake_order_tools):
    """A slightly different name is not a fuzzy match — it is unknown."""
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            for name in ("upstream_get_orders", "UPSTREAM_GET_ORDER",
                         "get_order", "upstream_get_order_x"):
                result = await asyncio.to_thread(
                    logix.run, {"call": name, "with": {}},
                )
                assert not result.ok, f"{name!r} unexpectedly resolved"
                assert result.errors[0].code == "UNKNOWN_CAPABILITY"
            assert client.calls == []
        finally:
            await proxy.shutdown()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@mcp_available
def test_startup_enters_client(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        assert not client.entered
        await proxy.startup()
        assert client.entered
        await proxy.shutdown()
        assert client.exited

    asyncio.run(run())


@mcp_available
def test_startup_populates_registry(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            assert set(logix.registry.names()) == {
                "upstream_get_order", "upstream_issue_refund",
            }
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_upstream_tool_names_accessor(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            names = proxy.upstream_tool_names
            assert "upstream_get_order" in names
            assert "upstream_issue_refund" in names
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_double_startup_raises(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            with pytest.raises(RuntimeError, match="startup.*twice"):
                await proxy.startup()
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_shutdown_without_startup_is_safe(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        # Never started; shutdown must not raise.
        await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_run_before_startup_raises(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    with pytest.raises(RuntimeError, match="startup"):
        proxy.run()