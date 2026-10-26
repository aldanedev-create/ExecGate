"""
Shared fixtures and helpers for the MCP integration test suite.

Includes:

- ``FakeMCPTool`` and ``FakeMCPClient`` — minimal MCP-shaped stubs so
  proxy tests can exercise the full startup/serve/shutdown path without
  a live upstream server.
- ``mcp_available`` — a marker for tests that specifically need FastMCP
  to be importable (which it is, given ``[mcp]`` extra).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

# FastMCP is a hard dependency of execgate_mcp, but guard anyway so tests
# fail with a clear message rather than a cryptic import error.
try:
    import fastmcp  # noqa: F401

    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False

mcp_available = pytest.mark.skipif(not HAS_FASTMCP, reason="execgate_mcp requires fastmcp")


# ---------------------------------------------------------------------------
# Minimal MCP-shaped stubs
# ---------------------------------------------------------------------------


@dataclass
class FakeMCPTool:
    """The subset of ``mcp.types.Tool`` the proxy reads."""

    name: str
    description: str
    inputSchema: dict[str, Any]  # noqa: N815


@dataclass
class FakeTextContent:
    """The subset of an MCP text content block the proxy reads."""

    text: str


@dataclass
class FakeCallToolResult:
    """The subset of ``mcp.types.CallToolResult`` the proxy reads."""

    content: list[FakeTextContent] = field(default_factory=list)
    isError: bool = False  # noqa: N815


class FakeMCPClient:
    """
    An async MCP client that returns configured tools on ``list_tools``
    and records ``call_tool`` invocations.

    Implements exactly the surface ``execgate_mcp.upstream`` and
    ``execgate_mcp.proxy`` depend on: ``__aenter__``, ``__aexit__``,
    ``list_tools``, ``call_tool``.

    Behavior:

    - ``tools`` are returned from ``list_tools()`` unchanged.
    - ``call_tool(name, arguments)`` records ``(name, arguments)`` and
      returns ``call_results[name]`` if present, else a default result
      whose text is ``'{"called": "<name>"}'``.
    - ``raise_on_call[name]`` raises the configured exception during
      ``call_tool`` — useful for failure-path tests.
    - ``entered`` / ``exited`` track lifecycle calls.
    """

    def __init__(
        self,
        tools: list[FakeMCPTool],
        *,
        call_results: dict[str, FakeCallToolResult] | None = None,
        raise_on_call: dict[str, Exception] | None = None,
    ) -> None:
        self._tools = tools
        self._call_results = call_results or {}
        self._raise_on_call = raise_on_call or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> FakeMCPClient:
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited = True

    async def list_tools(self) -> list[FakeMCPTool]:
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> FakeCallToolResult:
        self.calls.append((name, dict(arguments)))
        if name in self._raise_on_call:
            raise self._raise_on_call[name]
        if name in self._call_results:
            return self._call_results[name]
        return FakeCallToolResult(content=[FakeTextContent(text=json.dumps({"called": name}))])


@pytest.fixture
def fake_order_tools() -> list[FakeMCPTool]:
    """A standard pair of upstream tools for proxy tests."""
    return [
        FakeMCPTool(
            name="upstream_get_order",
            description="Get an order from the upstream service.",
            inputSchema={
                "type": "object",
                "properties": {"order_id": {"type": "integer"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
        ),
        FakeMCPTool(
            name="upstream_issue_refund",
            description="Issue a refund through the upstream service.",
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
