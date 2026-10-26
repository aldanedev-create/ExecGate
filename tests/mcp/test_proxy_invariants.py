"""
Proxy: live-state invariants fire before forwarding.

The wrapped capability behaves identically to any other registered
capability from Logix's perspective. ``logix.authorize(cap, check=...)``
runs in the recheck window before the handler (and thus before the
upstream call) is invoked.
"""

from __future__ import annotations

import asyncio

import pytest

from logiq import Allow, Deny, Logix
from logiq_mcp.proxy import LogixMCPProxy

from mcp_support import FakeMCPClient, mcp_available


@mcp_available
def test_invariant_denies_before_forwarding(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            # Attach an invariant to the wrapped capability.
            logix.authorize(
                "upstream_issue_refund",
                check=lambda args, ctx: Deny("BLOCKED", "not today"),
            )

            result = await asyncio.to_thread(
                logix.run,
                {"call": "upstream_issue_refund",
                 "with": {"order_id": 1, "amount": 5.0}},
            )
            assert not result.ok
            assert result.errors[0].code == "POLICY_REJECTED"
            assert client.calls == []
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_invariant_allow_permits_forwarding(fake_order_tools):
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            logix.authorize(
                "upstream_issue_refund",
                check=lambda args, ctx: Allow(),
            )

            result = await asyncio.to_thread(
                logix.run,
                {"call": "upstream_issue_refund",
                 "with": {"order_id": 1, "amount": 5.0}},
            )
            assert result.ok
            assert len(client.calls) == 1
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_invariant_sees_correct_arguments(fake_order_tools):
    """The invariant receives the resolved (validated) arguments — not
    the raw plan args."""
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    seen_args: list[dict] = []

    async def run():
        await proxy.startup()
        try:
            def capture(args, ctx):
                seen_args.append(dict(args))
                return Allow()

            logix.authorize("upstream_issue_refund", check=capture)

            await asyncio.to_thread(
                logix.run,
                {"call": "upstream_issue_refund",
                 "with": {"order_id": 502, "amount": 42.5}},
            )
            assert seen_args == [{"order_id": 502, "amount": 42.5}]
        finally:
            await proxy.shutdown()

    asyncio.run(run())


@mcp_available
def test_invariant_crashing_denies_forwarding(fake_order_tools):
    """A crashing invariant must never permit forwarding."""
    logix = Logix()
    client = FakeMCPClient(fake_order_tools)
    proxy = LogixMCPProxy(logix, client)

    async def run():
        await proxy.startup()
        try:
            def crash(args, ctx):
                raise RuntimeError("state store down")

            logix.authorize("upstream_issue_refund", check=crash)

            result = await asyncio.to_thread(
                logix.run,
                {"call": "upstream_issue_refund",
                 "with": {"order_id": 1, "amount": 5.0}},
            )
            assert not result.ok
            assert result.errors[0].code == "AUTHORIZATION_FAILED"
            assert client.calls == []
        finally:
            await proxy.shutdown()

    asyncio.run(run())