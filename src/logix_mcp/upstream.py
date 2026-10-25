"""
Fetch and wrap upstream MCP tools as native Logix capabilities.

Used by ``LogixMCPProxy``. Two functions:

- ``fetch_upstream_tools(client)`` — one round-trip to the upstream
  server's ``tools/list``, returns the tools.
- ``wrap_upstream_tool(tool, client, loop, logix)`` — build a
  ``Capability`` whose handler forwards to the upstream server.

The bridge between Logix's sync handler signature and MCP's async
client is ``asyncio.run_coroutine_threadsafe(coro, loop)``: the handler
runs inside a worker thread (spawned by ``asyncio.to_thread`` in
``server.py``), schedules the coroutine on the main event loop, and
blocks until it completes. This is correct because the main loop is
free while the worker thread runs — a deadlock would require the loop to
be blocked by the same thread, which ``to_thread`` prevents.

The proxy relies on ``capability.snapshot_hash()`` catching registry
changes between verify and execute. If the upstream server revokes a
tool mid-flight, the executor aborts with ``POLICY_REJECTED`` rather
than forwarding to an unknown capability.
"""

from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from logix.capabilities import Capability

from logix_mcp.adapter import extract_mcp_result_value, mcp_schema_to_logix

if TYPE_CHECKING:
    from logix.engine import Logix

__all__ = ["fetch_upstream_tools", "wrap_upstream_tool"]


async def fetch_upstream_tools(client: Any) -> list[Any]:
    """
    Fetch ``tools/list`` from an open MCP client.

    Accepts any object with an awaitable ``list_tools()``. Returns the
    ``tools`` attribute of the response, or the response itself if it is
    already a list (for compatibility with client variants that unwrap
    it).
    """
    response = await client.list_tools()
    tools = getattr(response, "tools", response)
    if not isinstance(tools, list):
        raise TypeError(
            f"expected tools/list to yield a list; got {type(tools).__name__}"
        )
    return tools


def wrap_upstream_tool(
    tool: Any,
    *,
    client: Any,
    loop: asyncio.AbstractEventLoop,
    logix: "Logix",
    timeout_seconds: float = 120.0,
) -> Capability:
    """
    Build a native ``Capability`` that wraps one upstream MCP tool.

    The capability's handler, when invoked by the Logix executor, calls
    ``client.call_tool(name, kwargs)`` on the upstream server, waits for
    the result, and returns a JSON-compatible value extracted from the
    MCP response.

    Args:
        tool: an MCP ``Tool`` object with ``name``, ``description``, and
            ``inputSchema``.
        client: the open MCP client.
        loop: the running event loop (from ``asyncio.get_running_loop()``
            at proxy startup).
        logix: the engine that owns this capability. Used only for the
            name lookup in error paths.
        timeout_seconds: per-call timeout for the upstream request. Raise
            this if the upstream is known to be slow.

    Raises:
        ValueError: if the upstream tool's ``inputSchema`` cannot be
            converted to a Logix ``ObjectType`` (see
            ``adapter.mcp_schema_to_logix`` for supported / unsupported
            keywords).
    """
    name = getattr(tool, "name", None)
    if not isinstance(name, str) or not name:
        raise ValueError(f"upstream tool has invalid name: {name!r}")

    description = getattr(tool, "description", "") or ""
    input_schema_dict = getattr(tool, "inputSchema", None)
    if not isinstance(input_schema_dict, dict):
        raise ValueError(
            f"upstream tool {name!r} has no inputSchema dict"
        )

    input_schema = mcp_schema_to_logix(input_schema_dict)

    def handler(**kwargs: Any) -> Any:
        # Runs in a worker thread (see server.py). Schedule the async
        # upstream call on the main loop and wait for the result.
        coro = client.call_tool(name, kwargs)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            upstream_result = future.result(timeout=timeout_seconds)
        except TimeoutError:
            raise TimeoutError(
                f"upstream tool {name!r} timed out after "
                f"{timeout_seconds}s"
            ) from None
        return extract_mcp_result_value(upstream_result)

    return Capability(
        name=name,
        description=description,
        handler=handler,
        input_schema=input_schema,
        output_schema=None,
        effects="write",           # upstream tools are untrusted by default
        requires_approval=False,
        idempotent=False,
    )