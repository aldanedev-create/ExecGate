"""
Proxy: approval gating before forwarding.

``logix.require_approval("upstream_tool")`` gates the wrapped capability
on an ``ApprovalToken`` exactly like any native capability. No token →
``APPROVAL_REQUIRED`` and the upstream is never called.
"""

from __future__ import annotations

import asyncio

from logiq import Logix
from logiq.approval import issue
from logiq_mcp.proxy import LogixMCPProxy

from .mcp_support import FakeMCPClient, mcp_available


@mcp_available
def test_approval_required_blocks_forwarding(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            logix.require_approval("upstream_issue_refund")

            result = await asyncio.to_thread(
                logix.run,
                {"call": "upstream_issue_refund", "with": {"order_id": 1, "amount": 5.0}},
            )
            assert not result.ok
            assert result.errors[0].code == "APPROVAL_REQUIRED"
            assert client.calls == []
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_valid_token_permits_forwarding(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    ctx = logix.context(principal="alice")
    args = {"order_id": 1, "amount": 5.0}

    async def run():
        await proxy.startup()
        try:
            logix.require_approval("upstream_issue_refund")

            report = logix.verify(
                {"call": "upstream_issue_refund", "with": args},
                context=ctx,
            )
            assert report.ok

            token = issue(
                capability="upstream_issue_refund",
                args=args,
                context=ctx,
                issuer="human:alice",
            )
            result = await asyncio.to_thread(
                logix.execute,
                report.verified_plan,
                context=ctx,
                approval=token,
            )
            assert result.ok, result.errors
            assert len(client.calls) == 1
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_mismatched_token_blocks_forwarding(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    ctx = logix.context(principal="alice")
    # Token bound to a different amount.
    wrong_token = issue(
        capability="upstream_issue_refund",
        args={"order_id": 1, "amount": 999.0},
        context=ctx,
        issuer="human:alice",
    )

    async def run():
        await proxy.startup()
        try:
            logix.require_approval("upstream_issue_refund")

            report = logix.verify(
                {"call": "upstream_issue_refund", "with": {"order_id": 1, "amount": 5.0}},
                context=ctx,
            )
            result = await asyncio.to_thread(
                logix.execute,
                report.verified_plan,
                context=ctx,
                approval=wrong_token,
            )
            assert not result.ok
            assert result.errors[0].code == "APPROVAL_REQUIRED"
            assert client.calls == []
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_token_from_wrong_principal_blocks(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    alice_ctx = logix.context(principal="alice")
    bob_ctx = logix.context(principal="bob")
    token = issue(
        capability="upstream_issue_refund",
        args={"order_id": 1, "amount": 5.0},
        context=alice_ctx,
        issuer="human:alice",
    )

    async def run():
        await proxy.startup()
        try:
            logix.require_approval("upstream_issue_refund")

            report = logix.verify(
                {"call": "upstream_issue_refund", "with": {"order_id": 1, "amount": 5.0}},
                context=bob_ctx,
            )
            result = await asyncio.to_thread(
                logix.execute,
                report.verified_plan,
                context=bob_ctx,
                approval=token,
            )
            assert not result.ok
            assert result.errors[0].code == "APPROVAL_REQUIRED"
            assert client.calls == []
        finally:
            await proxy.shutdown()

    asyncio.run(run())
