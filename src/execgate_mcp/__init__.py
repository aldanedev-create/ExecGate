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
``ToolSpec`` from ``execgate.tools``, ``Result`` / ``Error`` from
``execgate.results`` / ``execgate.errors``, and public engine APIs. They never
import from ``execgate.verifier``, ``execgate.executor``, or ``execgate.ir``.

This package requires FastMCP 4 (which is built on the official MCP
Python SDK v2). Install with::

    pip install "logiq[mcp]"
"""

from __future__ import annotations

from typing import Any

try:
    import fastmcp as _fastmcp
except ImportError as e:  # pragma: no cover — tested via test_core_without_mcp
    raise ImportError(
        'execgate_mcp requires fastmcp>=4; install with: pip install "logiq[mcp]"'
    ) from e

if not hasattr(_fastmcp, "FastMCP"):
    raise ImportError(
        f"execgate_mcp requires fastmcp>=4; installed version lacks FastMCP "
        f"(module: {_fastmcp.__file__})"
    )

from execgate_mcp.adapter import (
    extract_mcp_result_value,
    format_errors_for_mcp,
    from_mcp_call,
    mcp_schema_to_logix,
    result_to_mcp_response,
    schema_errors_to_errors,
    tool_spec_to_mcp_dict,
)
from execgate_mcp.proxy import LogixMCPProxy
from execgate_mcp.server import LogixMCPServer
from execgate_mcp.upstream import fetch_upstream_tools, wrap_upstream_tool

__all__ = [
    "LogixMCPProxy",
    # Server + proxy
    "LogixMCPServer",
    # Adapter
    "extract_mcp_result_value",
    # Upstream
    "fetch_upstream_tools",
    "format_errors_for_mcp",
    "from_mcp_call",
    "mcp_schema_to_logix",
    "result_to_mcp_response",
    "schema_errors_to_errors",
    "tool_spec_to_mcp_dict",
    "wrap_upstream_tool",
]


def install(logiq: Any) -> None:
    """
    Explicit startup assertion.

    Importing this package already ensures FastMCP is available. This
    function exists for symmetry with ``execgate_pydantic.install`` and for
    applications that want to fail loudly at startup if MCP support was
    expected but the extra was not installed.

    The ``logiq`` argument is accepted for forward compatibility
    (per-engine configuration); 0.1.0 has no per-engine flag.
    """
    _ = logiq
