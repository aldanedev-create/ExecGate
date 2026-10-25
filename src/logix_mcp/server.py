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
wrong types receives ``SCHEMA_VALIDATION_FAILED`` from ``logix.run``. The
guarantee lives in Logix, not in the MCP advertisement.

The ``asyncio.to_thread`` wrapper is load-bearing: Logix handlers are
synchronous, but blocking the FastMCP event loop on a slow handler would
freeze the whole server. Running the sync ``logix.run`` in a thread keeps
the loop responsive to other MCP requests.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable

from logix.context import ExecutionContext
from logix.engine import Logix

from logix_mcp.adapter import (
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

        from logix import Logix
        from logix_mcp import LogixMCPServer

        logix = Logix()

        @logix.capability
        def add(a: int, b: int) -> int:
            "Add two integers."
            return a + b

        server = LogixMCPServer(logix, name="math")
        server.run()  # stdio by default

    The engine's capability registry must be fully populated before
    ``LogixMCPServer(logix)`` is constructed. Registering capabilities
    after the server starts does not add new tools.
    """

    def __init__(
        self,
        logix: Logix,
        *,
        name: str = "logix",
        context_factory: "Callable[[], ExecutionContext] | None" = None,
    ) -> None:
        """
        Args:
            logix: the engine to expose. Its current capabilities are
                registered as MCP tools immediately.
            name: the MCP server name reported to clients.
            context_factory: a zero-argument callable returning an
                ``ExecutionContext`` per tool call. Defaults to a context
                with ``principal="mcp"``. Override to bind requests to a
                real principal (e.g., from MCP auth metadata).
        """
        from fastmcp import FastMCP

        self._logix = logix
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

        FastMCP 4.0.8's ``add_tool`` derives tool name from the callable's
        ``__name__``, description from ``__doc__``, and input schema from
        the callable's signature. The handler built by ``_build_handler``
        already carries the correct ``__name__`` and ``__doc__``; the
        signature is ``**kwargs``, which FastMCP maps to a permissive
        object schema.

        A future FastMCP release may restore explicit schema registration.
        When it does, this method can pass ``parameters=spec.input_schema``
        through ``Tool.from_function``. For 4.0.8, permissive MCP schema
        plus strict Logix validation is the working combination.
        """
        handler = self._build_handler(spec.name)
        try:
            self._mcp.add_tool(handler)
        except TypeError as e:
            # If the API changed again, surface it with context.
            raise RuntimeError(
                f"cannot register MCP tool {spec.name!r} on this FastMCP "
                f"version: {e}. Reported handler signature: "
                f"name={handler.__name__!r}. If a newer FastMCP API is "
                f"required, update logix_mcp._register_one_tool."
            ) from e

        logger.info(
            "Registered MCP tool %r. MCP-side schema is permissive "
            "(**kwargs); Logix enforces the real input schema on every call.",
            spec.name,
        )

    def _build_handler(self, capability_name: str):
        """
        Build an async FastMCP tool handler for one capability.

        The handler's ``__name__`` IS the tool name (FastMCP reads it for
        dispatch and advertisement). It must not be prefixed.
        """
        logix = self._logix
        ctx_factory = self._context_factory

        async def handler(**kwargs: Any) -> Any:
            plan = from_mcp_call(capability_name, kwargs)
            ctx = ctx_factory()
            # Run the sync Logix pipeline off the event loop. Blocking the
            # loop on a slow handler would freeze all other MCP requests.
            result = await asyncio.to_thread(
                functools.partial(logix.run, plan, context=ctx)
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