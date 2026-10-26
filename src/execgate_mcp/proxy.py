"""
MCP proxy mode: put Logix between an MCP client and an untrusted
upstream MCP server.

The proxy is composed of three phases:

1. **Startup.** Connect to the upstream server, fetch ``tools/list``,
   wrap each tool as a native ``Capability``, and register those in the
   engine. This is what turns upstream tools into *verified* tools —
   every subsequent call must resolve against the local registry.

2. **Serve.** Run an MCP server (Mode 1) exposing the wrapped
   capabilities. Client calls flow through the full Logix pipeline:
   parse, grounding, verify, recheck, execute. Only if execution
   succeeds does the wrapper handler reach out to upstream.

3. **Shutdown.** Close the upstream client.

Lifecycle::

    proxy = LogixMCPProxy(logiq, "http://upstream/mcp")
    await proxy.startup()
    try:
        await proxy.run_async()          # or proxy.run() blocking
    finally:
        await proxy.shutdown()
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from execgate.context import ExecutionContext
from execgate.engine import Logix
from execgate_mcp.server import LogixMCPServer
from execgate_mcp.upstream import fetch_upstream_tools, wrap_upstream_tool

__all__ = ["LogixMCPProxy"]


class LogixMCPProxy:
    """
    An MCP proxy that verifies every call through Logix before
    forwarding it to an upstream MCP server.

    The wrapped upstream tools land in ``execgate.registry``. Anything not
    in the registry — a tool the client invents, or a tool that was
    registered after startup — is rejected with ``UNKNOWN_CAPABILITY``
    before reaching upstream.
    """

    def __init__(
        self,
        logiq: Logix,
        upstream: Any,
        *,
        name: str = "logiq-proxy",
        context_factory: Callable[[], ExecutionContext] | None = None,
    ) -> None:
        """
        Args:
            logiq: the engine whose registry will hold the wrapped tools.
                Must be empty (or contain only tools the proxy is
                expected to compose with) at ``startup()`` time.
            upstream: an MCP server URL string, or a pre-configured
                object with an ``__aenter__`` / ``__aexit__`` contract
                and an awaitable ``list_tools()``.
            name: the MCP server name reported to clients.
            context_factory: as in ``LogixMCPServer``.
        """
        self._logix = logiq
        self._upstream = upstream
        self._name = name
        self._context_factory = context_factory
        self._client: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: LogixMCPServer | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        """
        Connect to upstream, fetch tools, register wrapper capabilities.

        Idempotent-safe: raises if called twice without an intervening
        ``shutdown()``. On failure, closes the client and leaves the
        proxy in a clean state.
        """
        if self._server is not None:
            raise RuntimeError("startup() called twice; call shutdown() first")

        self._loop = asyncio.get_running_loop()

        if isinstance(self._upstream, str):
            from fastmcp import Client

            self._client = Client(self._upstream)
        else:
            self._client = self._upstream

        entered = False
        try:
            await self._client.__aenter__()
            entered = True

            tools = await fetch_upstream_tools(self._client)

            # Wrap and register each upstream tool.
            for tool in tools:
                cap = wrap_upstream_tool(
                    tool,
                    client=self._client,
                    loop=self._loop,
                    logiq=self._logix,
                )
                self._logix._registry.add(cap)

            # Build the outer MCP server over the just-populated registry.
            self._server = LogixMCPServer(
                self._logix,
                name=self._name,
                context_factory=self._context_factory,
            )
        except Exception:
            if entered and self._client is not None:
                await self._client.__aexit__(None, None, None)
            self._client = None
            self._server = None
            raise

    async def shutdown(self) -> None:
        """Close the upstream client. Safe to call if not started."""
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
        self._client = None
        self._server = None

    # ------------------------------------------------------------------
    # Serving
    # ------------------------------------------------------------------

    async def run_async(self, **kwargs: Any) -> None:
        """Run the proxy as an MCP server (async)."""
        if self._server is None:
            raise RuntimeError("call startup() before run_async()")
        await self._server.run_async(**kwargs)

    def run(self, **kwargs: Any) -> None:
        """Run the proxy as an MCP server (blocking)."""
        if self._server is None:
            raise RuntimeError("call startup() before run()")
        self._server.run(**kwargs)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def server(self) -> LogixMCPServer:
        """The underlying ``LogixMCPServer`` (after startup)."""
        if self._server is None:
            raise RuntimeError("call startup() first")
        return self._server

    @property
    def upstream_tool_names(self) -> list[str]:
        """Names of the wrapped upstream tools (after startup)."""
        return self._logix.registry.names()
