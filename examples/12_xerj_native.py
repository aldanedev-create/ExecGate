"""
XERJ search as a native Logiq capability.

Run:
    python examples/12_xerj_native.py

Requires:
    pip install httpx
    A XERJ node running locally (or at XERJ_URL below)

Demonstrates:
  - a native capability that calls XERJ's Elasticsearch-compatible API
  - typing narrower than XERJ's permissive schema: Literal["code", "docs"]
  - per-tenant scoping via an invariant
  - output validation on the search results

If XERJ is not available, the script prints the capability's schema and
exits — the rest of the file (the shape) is still useful.

See docs/integrations/xerj.md for the design rationale.
"""

import os
import sys

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from typing import Annotated, Literal

from execgate import Logix, Deny
from execgate.schemas import Gt, Le, MaxLength, MinLength


XERJ_URL = os.environ.get("XERJ_URL", "http://localhost:7700")
XERJ_API_KEY = os.environ.get("XERJ_API_KEY", "")


def main() -> None:
    logix = Logix()

    @logix.capability(effects="read")
    def xerj_search(
        query: Annotated[str, MinLength(1), MaxLength(200)],
        index: Literal["code", "docs"] = "code",
        size: Annotated[int, Gt(0), Le(20)] = 10,
    ) -> list[dict[str, str]]:
        "Search the XERJ index for code or docs."
        response = httpx.post(
            f"{XERJ_URL}/{index}-*/_search",
            headers={"Authorization": f"ApiKey {XERJ_API_KEY}"},
            json={
                "query": {"match": {"body": query}},
                "size": size,
                "_source": ["ax_path", "language", "symbols", "defs"],
            },
            timeout=5.0,
        )
        response.raise_for_status()
        hits = response.json().get("hits", {}).get("hits", [])
        return [
            {
                "path": h.get("_source", {}).get("ax_path", ""),
                "language": h.get("_source", {}).get("language", ""),
                "symbols": ",".join(h.get("_source", {}).get("symbols", [])),
            }
            for h in hits
        ]

    # Per-tenant scoping — XERJ has no concept of "which caller sees which index."
    def tenant_scope(args, ctx):
        allowed = {
            "internal": {"code", "docs"},
            "partner": {"docs"},
            "public": {"docs"},
        }.get(ctx.tenant, set())
        if args["index"] not in allowed:
            return Deny("INDEX_FORBIDDEN", "not available to this tenant")
        return None

    logix.authorize(xerj_search, check=tenant_scope)

    # --- The narrowed schema ---
    print("=== The capability's schema (narrower than XERJ's MCP schema) ===")
    spec = logix.tools.for_capability("xerj_search")
    print(spec.input_schema)

    # --- Behavior: unknown index rejected by schema ---
    print("\n=== Unknown index rejected by schema ===")
    result = logix.run(
        {
            "call": "xerj_search",
            "with": {"query": "merge_segments", "index": "_memory"},
        }
    )
    print(f"code={result.errors[0].code}")

    # --- Behavior: oversized size rejected by schema ---
    print("\n=== Oversized size rejected by schema ===")
    result = logix.run(
        {
            "call": "xerj_search",
            "with": {"query": "merge_segments", "size": 1000},
        }
    )
    print(f"code={result.errors[0].code}")

    # --- Behavior: tenant scoping ---
    print("\n=== Tenant scoping ===")
    public_ctx = logix.context(principal="u1", tenant="public")
    result = logix.run(
        {"call": "xerj_search", "with": {"query": "merge", "index": "code"}},
        context=public_ctx,
    )
    print(f"public tenant, code index: code={result.errors[0].code}")
    print("  (public tenant cannot read 'code' — the invariant denies it.)")

    # --- Live call (requires XERJ) ---
    if not HAS_HTTPX:
        print("\n(httpx not installed; skipping live call. Install with: pip install httpx)")
        return
    if not XERJ_API_KEY:
        print("\n(XERJ_API_KEY not set; skipping live call.)")
        return

    print("\n=== Live call ===")
    internal_ctx = logix.context(principal="u1", tenant="internal")
    result = logix.run(
        {"call": "xerj_search", "with": {"query": "merge", "index": "code"}},
        context=internal_ctx,
    )
    if result.ok:
        print(f"Results: {len(result.value)} hits")
        for hit in result.value[:3]:
            print(f"  {hit['path']} ({hit['language']})")
    else:
        print(f"Error: {result.errors[0].code} {result.errors[0].message}")


if __name__ == "__main__":
    main()
