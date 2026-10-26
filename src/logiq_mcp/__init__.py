"""
MCP integration for Logix.

Two modes:

- **Server** (``LogixMCPServer``): expose a Logix engine's capabilities
  as MCP tools. Any MCP client can discover and call them; the Logix
  pipeline runs on every call.

- **Proxy** (``LogixMCPProxy``): wrap an untrusted upstream MCP server,
  verify each call through Logix before forwarding, and serve the
  verified capabilities to MCP clients.

Both modes are leaf nodes (ADR-0006, ADR-0007): they import only
``ToolSpec`` from ``logiq.tools``, ``Result`` / ``Error`` from
``logiq.results`` / ``logiq.errors``, and public engine APIs. They never
import from ``logiq.verifier``, ``logiq.executor``, or ``logiq.ir``.

This package requires FastMCP 4 (which is built on the official MCP
Python SDK v2). Install with::

    pip install "logiq[mcp]"
"""

from __future__ import annotations

try:
    import fastmcp as _fastmcp
except ImportError as e:  # pragma: no cover — tested via test_core_without_mcp
    raise ImportError(
        "logiq_mcp requires fastmcp>=4; install with: "
        "pip install \"logiq[mcp]\""
    ) from e

if not hasattr(_fastmcp, "FastMCP"):
    raise ImportError(
        f"logiq_mcp requires fastmcp>=4; installed version lacks FastMCP "
        f"(module: {_fastmcp.__file__})"
    )

from logiq_mcp.adapter import (
    extract_mcp_result_value,
    format_errors_for_mcp,
    from_mcp_call,
    mcp_schema_to_logix,
    result_to_mcp_response,
    schema_errors_to_errors,
    tool_spec_to_mcp_dict,
)
from logiq_mcp.proxy import LogixMCPProxy
from logiq_mcp.server import LogixMCPServer
from logiq_mcp.upstream import fetch_upstream_tools, wrap_upstream_tool

__all__ = [
    # Server + proxy
    "LogixMCPServer",
    "LogixMCPProxy",
    # Upstream
    "fetch_upstream_tools",
    "wrap_upstream_tool",
    # Adapter
    "extract_mcp_result_value",
    "format_errors_for_mcp",
    "from_mcp_call",
    "mcp_schema_to_logix",
    "result_to_mcp_response",
    "schema_errors_to_errors",
    "tool_spec_to_mcp_dict",
]


def install(logiq) -> None:
    """
    Explicit startup assertion.

    Importing this package already ensures FastMCP is available. This
    function exists for symmetry with ``logiq_pydantic.install`` and for
    applications that want to fail loudly at startup if MCP support was
    expected but the extra was not installed.

    The ``logiq`` argument is accepted for forward compatibility
    (per-engine configuration); 0.1.0 has no per-engine flag.
    """
    _ = logiq