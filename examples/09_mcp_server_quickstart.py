"""
Expose Logiq capabilities as an MCP server.

Run:
    python examples/09_mcp_server_quickstart.py

Requires:
    pip install "logiq[mcp]"
    (FastMCP 4.x is installed by the extra)

Demonstrates:
  - LogixMCPServer(logix)      — create a server
  - server.describe()           — inspect the tools/list payload
  - server.run()                — start the stdio MCP server

The script prints the tools/list payload, then (if invoked with
--serve) starts the stdio server. Without --serve, it just shows the
catalog — no subprocess is spawned, nothing blocks.

To use it with an MCP client (Claude Desktop, etc.), configure:

    {
      "mcpServers": {
        "logiq-example": {
          "command": "python",
          "args": ["examples/09_mcp_server_quickstart.py", "--serve"]
        }
      }
    }
"""

import sys

from execgate import Logix
from execgate_mcp import LogixMCPServer


def main() -> None:
    logix = Logix()

    @logix.capability(effects="read")
    def add(a: int, b: int) -> int:
        "Add two integers."
        return a + b

    @logix.capability(effects="read")
    def get_order(order_id: int) -> dict[str, float]:
        "Retrieve an order by its ID."
        return {"id": float(order_id), "total": 50.0}

    server = LogixMCPServer(logix, name="logiq-example")

    print("=== MCP tools/list payload ===")
    for tool in server.describe():
        print(f"\nName: {tool['name']}")
        print(f"Description: {tool['description']}")
        print(f"Schema: {tool['inputSchema']}")

    if "--serve" in sys.argv:
        print("\n=== Starting stdio MCP server (Ctrl-C to stop) ===")
        server.run()
    else:
        print(
            "\n(To actually serve MCP, run with --serve. Without it, this "
            "script only prints the catalog — no subprocess is spawned.)"
        )


if __name__ == "__main__":
    main()