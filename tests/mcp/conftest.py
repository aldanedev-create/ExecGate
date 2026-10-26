"""
Pytest hook-up for the MCP suite.

Helpers and stubs live in ``mcp_support`` (importable as a top-level
module because pytest puts this directory on ``sys.path``). They are not
kept here, and ``tests/mcp`` is deliberately *not* a package: a package
named ``mcp`` would shadow the real ``mcp`` library that FastMCP imports.
"""

from .mcp_support import fake_order_tools, mcp_available  # noqa: F401
