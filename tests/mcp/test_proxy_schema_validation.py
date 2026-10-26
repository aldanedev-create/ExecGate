"""
Proxy: schema violations rejected before forwarding.

The wrapped capability's ``input_schema`` is derived from the upstream
tool's ``inputSchema``. Invalid arguments are rejected at verify time —
the upstream client never sees them.
"""

from __future__ import annotations

import asyncio

import pytest

from logiq import Logix
from logiq_mcp.proxy import LogixMCPProxy

from mcp_support import FakeMCPClient, mcp_available


@mcp_available
def test_wrong_type_rejected_before_forwarding(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            result = await asyncio.to_thread(
                logix.run,
                {"call": "upstream_get_order", "with": {"order_id": "not-an-int"}},
            )
            assert not result.ok
            assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"
            assert client.calls == []
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_missing_required_arg_rejected(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            result = await asyncio.to_thread(
                logix.run,
                {"call": "upstream_get_order", "with": {}},
            )
            assert not result.ok
            assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"
            assert client.calls == []
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_extra_arg_rejected(fake_order_tools):
    """``additionalProperties: false`` in the upstream schema is preserved."""
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            result = await asyncio.to_thread(
                logix.run,
                {"call": "upstream_get_order",
                 "with": {"order_id": 1, "evil": "payload"}},
            )
            assert not result.ok
            assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"
            assert client.calls == []
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_valid_args_forwarded(fake_order_tools):
    """Sanity: valid args do reach upstream."""
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            result = await asyncio.to_thread(
                logix.run,
                {"call": "upstream_issue_refund",
                 "with": {"order_id": 1, "amount": 5.0}},
            )
            assert result.ok
            assert client.calls == [
                ("upstream_issue_refund", {"order_id": 1, "amount": 5.0}),
            ]
        finally:
            await proxy.shutdown()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Startup: unsupported upstream schemas
# ---------------------------------------------------------------------------

@mcp_available
def test_startup_fails_on_unsupported_schema():
    """If upstream declares a schema we can't faithfully wrap, startup
    must fail — not silently downgrade to a permissive schema."""
    from mcp_support import FakeMCPClient, FakeMCPTool

    tools = [
        FakeMCPTool(
            name="bad_tool",
            description="",
            inputSchema={
                "type": "object",
                "properties": {"x": {"$ref": "#/defs/X"}},  # unsupported
            },
        ),
    ]

    logix = Logix()
    client = FakeMCPClient(tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        with pytest.raises(ValueError, match=r"\$ref|unsupported"):
            await proxy.startup()

    asyncio.run(run())

    # Client was cleaned up on failure.
    assert client.exited