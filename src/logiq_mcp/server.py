"""
MCP server mode: expose a Logix engine's capabilities as MCP tools.

FastMCP 4.0.8's ``add_tool(fn)`` introspects the callable for the tool
name (from ``__name__``), description (from ``__doc__``), and input schema
(from the function signature). It does not accept explicit
``name=``/``description=``/``parameters=`` kwargs, and its ``Tool``
constructor rejects a ``fn`` field.

Given that constraint, this module registers each capability via:

    handler.__name__ = capability_name
    handler.__doc__  = description
    mcp.add_tool(handler)

Consequence: the MCP-side schema is inferred from the handler's signature
(``**kwargs``), so it is permissive on the wire. **Logix still enforces
the real schema at execution time** — a client that sends extra args or
wrong types receives ``SCHEMA_VALIDATION_FAILED`` from ``logiq.run``. The
guarantee lives in Logix, not in the MCP advertisement.

The ``asyncio.to_thread`` wrapper is load-bearing: Logix handlers are
synchronous, but blocking the FastMCP event loop on a slow handler would
freeze the whole server. Running the sync ``logiq.run`` in a thread keeps
the loop responsive to other MCP requests.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable

from logiq.context import ExecutionContext
from logiq.engine import Logix

from logiq_mcp.adapter import (
    from_mcp_call,
    result_to_mcp_response,
    tool_spec_to_mcp_dict,
)

__all__ = ["LogixMCPServer"]

logger = logging.getLogger(__name__)


class LogixMCPServer:
    """
    An MCP server that exposes a ``Logix`` engine's capabilities as tools.

    Usage::

        from logiq import Logix
        from logiq_mcp import LogixMCPServer

        logiq = Logix()

        @logiq.capability
        def add(a: int, b: int) -> int:
            "Add two integers."
            return a + b

        server = LogixMCPServer(logiq, name="math")
        server.run()  # stdio by default

    The engine's capability registry must be fully populated before
    ``LogixMCPServer(logiq)`` is constructed. Registering capabilities
    after the server starts does not add new tools.
    """

    def __init__(
        self,
        logiq: Logix,
        *,
        name: str = "logiq",
        context_factory: "Callable[[], ExecutionContext] | None" = None,
    ) -> None:
        """
        Args:
            logiq: the engine to expose. Its current capabilities are
                registered as MCP tools immediately.
            name: the MCP server name reported to clients.
            context_factory: a zero-argument callable returning an
                ``ExecutionContext`` per tool call. Defaults to a context
                with ``principal="mcp"``. Override to bind requests to a
                real principal (e.g., from MCP auth metadata).
        """
        from fastmcp import FastMCP

        self._logix = logiq
        self._name = name
        self._context_factory: Callable[[], ExecutionContext] = (
            context_factory
            if context_factory is not None
            else (lambda: ExecutionContext(principal="mcp"))
        )
        self._mcp = FastMCP(name)
        self._register_all_tools()

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def mcp(self) -> Any:
        """The underlying FastMCP instance, for advanced customisation."""
        return self._mcp

    def run(self, **kwargs: Any) -> None:
        """Run the server (blocking). Delegates to ``FastMCP.run``."""
        self._mcp.run(**kwargs)

    async def run_async(self, **kwargs: Any) -> None:
        """Run the server (async). Delegates to ``FastMCP.run_async``."""
        runner = getattr(self._mcp, "run_async", None)
        if runner is None:
            raise RuntimeError(
                "this FastMCP version has no run_async; use run() from a "
                "synchronous entry point"
            )
        await runner(**kwargs)

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_all_tools(self) -> None:
        for spec in self._logix.tools.describe():
            self._register_one_tool(spec)

    def _register_one_tool(self, spec: Any) -> None:
        """
        Register one ``ToolSpec`` as a FastMCP tool.

        Preferred path: register a ``Tool`` that advertises the real
        ``spec.input_schema`` and delegates to ``_build_handler``'s
        handler. FastMCP >= 4.1 rejects ``**kwargs`` callables, so this is
        the path that works on current releases, and it makes the MCP-side
        schema match the Logix catalog exactly.

        Fallback (FastMCP 4.0.x): register the ``**kwargs`` handler
        directly. That advertises a permissive MCP schema; Logix still
        enforces the real input schema on every call.
        """
        handler = self._build_handler(spec.name)

        tool = None
        try:
            tool = self._make_explicit_schema_tool(spec, handler)
        except (ImportError, TypeError, ValueError) as e:
            logger.debug(
                "explicit-schema registration unavailable for %r (%s); "
                "falling back to **kwargs handler", spec.name, e,
            )

        try:
            self._mcp.add_tool(tool if tool is not None else handler)
        except TypeError as e:
            # If the API changed again, surface it with context.
            raise RuntimeError(
                f"cannot register MCP tool {spec.name!r} on this FastMCP "
                f"version: {e}. Reported handler signature: "
                f"name={handler.__name__!r}. If a newer FastMCP API is "
                f"required, update logiq_mcp._register_one_tool."
            ) from e

        logger.info(
            "Registered MCP tool %r (%s schema); Logix enforces the real "
            "input schema on every call.",
            spec.name,
            "explicit" if tool is not None else "permissive **kwargs",
        )

    @staticmethod
    def _make_explicit_schema_tool(spec: Any, handler: Callable[..., Any]) -> Any:
        """Build a FastMCP ``Tool`` carrying ``spec.input_schema``."""
        from fastmcp.tools import Tool
        from pydantic import Field

        class _LogixTool(Tool):  # type: ignore[misc]
            handler: Any = Field(default=None, exclude=True)

            async def run(self, arguments: dict[str, Any]) -> Any:
                return self.convert_result(await self.handler(**arguments))

        return _LogixTool(
            name=spec.name,
            description=spec.description or f"Logix capability: {spec.name}",
            parameters=spec.input_schema,
            handler=handler,
        )

    def _build_handler(self, capability_name: str):
        """
        Build an async FastMCP tool handler for one capability.

        The handler's ``__name__`` IS the tool name (FastMCP reads it for
        dispatch and advertisement). It must not be prefixed.
        """
        logiq = self._logix
        ctx_factory = self._context_factory

        async def handler(**kwargs: Any) -> Any:
            plan = from_mcp_call(capability_name, kwargs)
            ctx = ctx_factory()
            # Run the sync Logix pipeline off the event loop. Blocking the
            # loop on a slow handler would freeze all other MCP requests.
            result = await asyncio.to_thread(
                functools.partial(logiq.run, plan, context=ctx)
            )
            return result_to_mcp_response(result)

        # FastMCP uses __name__ for the tool name. Set it to the capability
        # name — NOT a prefixed variant.
        handler.__name__ = capability_name
        handler.__qualname__ = capability_name
        handler.__doc__ = f"Logix capability: {capability_name}"
        return handler

    # ------------------------------------------------------------------
    # Convenience: raw tools/list output (bypasses FastMCP)
    # ------------------------------------------------------------------

    def describe(self) -> list[dict[str, Any]]:
        """
        Return the ``tools/list`` payload as plain dicts.

        Useful for tests and for applications that want to inspect the
        catalog without going through FastMCP. Does not require FastMCP.
        """
        return [
            tool_spec_to_mcp_dict(spec)
            for spec in self._logix.tools.describe()
        ]