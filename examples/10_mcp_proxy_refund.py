"""
Verify calls to an untrusted upstream MCP server.

Run:
    python examples/10_mcp_proxy_refund.py

Requires:
    pip install "logiq[mcp]"

Demonstrates:
  - LogixMCPProxy(logix, upstream)  — the proxy
  - proxy.startup()                  — fetch upstream tools, wrap them
  - logix.authorize(wrapped_tool, check=...)  — policy on wrapped tools
  - unknown tool rejected, invalid args rejected, policy denied — all
    before the upstream is called

This example uses a FakeMCPClient (an in-memory stub) so it runs
without a live upstream. To use with a real upstream, replace the stub
with fastmcp.Client("http://upstream/mcp") — the rest is identical.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from logiq import Logix, Deny
from logiq_mcp import LogixMCPProxy


# --- Upstream stub ---

@dataclass
class FakeMCPTool:
    name: str
    description: str
    inputSchema: dict[str, Any]


@dataclass
class FakeTextContent:
    text: str


@dataclass
class FakeCallToolResult:
    content: list[FakeTextContent] = field(default_factory=list)
    isError: bool = False


class FakeMCPClient:
    def __init__(self, tools: list[FakeMCPTool]):
        self._tools = tools
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *args):
        self.exited = True

    async def list_tools(self):
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        self.calls.append((name, dict(arguments)))
        return FakeCallToolResult(
            content=[FakeTextContent(text=json.dumps({"called": name, "args": arguments}))]
        )


async def main() -> None:
    logix = Logix()

    tools = [
        FakeMCPTool(
            name="upstream_get_order",
            description="Get an order from upstream.",
            inputSchema={
                "type": "object",
                "properties": {"order_id": {"type": "integer"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
        ),
        FakeMCPTool(
            name="upstream_issue_refund",
            description="Issue a refund through upstream.",
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer"},
                    "amount": {"type": "number"},
                },
                "required": ["order_id", "amount"],
                "additionalProperties": False,
            },
        ),
    ]
    client = FakeMCPClient(tools)

    proxy = LogixMCPProxy(logix, client)

    print("=== Startup ===")
    await proxy.startup()
    print(f"Registered: {logix.registry.names()}")

    # Attach a policy to the wrapped refund tool.
    def refund_policy(args, ctx):
        if ctx.principal != "admin":
            return Deny("NOT_ADMIN", "only admins can refund")
        return None

    logix.authorize("upstream_issue_refund", check=refund_policy)

    admin = logix.context(principal="admin")
    alice = logix.context(principal="alice")

    print("\n=== Unknown tool ===")
    result = await asyncio.to_thread(
        logix.run, {"call": "nonexistent", "with": {}}, context=admin,
    )
    print(f"code={result.errors[0].code}, upstream_calls={client.calls}")

    print("\n=== Invalid args ===")
    result = await asyncio.to_thread(
        logix.run,
        {"call": "upstream_get_order", "with": {"order_id": "not-an-int"}},
        context=admin,
    )
    print(f"code={result.errors[0].code}, upstream_calls={client.calls}")

    print("\n=== Policy denied ===")
    result = await asyncio.to_thread(
        logix.run,
        {"call": "upstream_issue_refund", "with": {"order_id": 1, "amount": 5.0}},
        context=alice,
    )
    print(f"code={result.errors[0].code}, message={result.errors[0].message}")
    print(f"upstream_calls={client.calls}")

    print("\n=== Allowed (admin) ===")
    result = await asyncio.to_thread(
        logix.run,
        {"call": "upstream_issue_refund", "with": {"order_id": 1, "amount": 5.0}},
        context=admin,
    )
    print(f"ok={result.ok}, upstream_calls={client.calls}")

    await proxy.shutdown()
    print(f"\n=== Shutdown ===\nclient.exited={client.exited}")


if __name__ == "__main__":
    asyncio.run(main())