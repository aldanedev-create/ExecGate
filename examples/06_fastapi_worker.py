"""
Framework-agnostic embedding.

Run:
    python examples/06_fastapi_worker.py

Demonstrates:
  - Logiq inside a FastAPI app
  - the same Logiq engine used from a background worker
  - FastAPI/Starlette is NOT a core dependency; this file is the only
    place it appears

Requires:
    pip install fastapi uvicorn

Start the server:
    uvicorn examples.06_fastapi_worker:app --reload

Send a plan:
    curl -X POST http://localhost:8000/run \
      -H "Content-Type: application/json" \
      -d '{"plan": {"call": "add", "with": {"a": 1, "b": 2}}}'
"""

from __future__ import annotations

import asyncio
import json

# These are NOT imported by the core. This file is the only FastAPI
# reference; logiq does not require it.
try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from execgate import Logix


logix = Logix()


@logix.capability
def add(a: int, b: int) -> int:
    "Add two integers."
    return a + b


@logix.capability(effects="read")
def get_order(order_id: int) -> dict[str, float]:
    "Retrieve an order."
    return {"id": float(order_id), "total": 50.0}


# --- Background worker: the same engine, called from a task ---
async def background_worker():
    """Simulates a periodic job that runs a plan."""
    while True:
        await asyncio.sleep(60)
        result = logix.run({"call": "get_order", "with": {"order_id": 1}})
        print(f"[worker] periodic result: {result.value}")


# --- FastAPI app ---
if HAS_FASTAPI:
    app = FastAPI(title="Logiq example")

    class RunRequest(BaseModel):
        plan: dict
        principal: str = "anonymous"

    @app.post("/run")
    def run_plan(req: RunRequest):
        ctx = logix.context(principal=req.principal)
        result = logix.run(req.plan, context=ctx)
        if not result.ok:
            raise HTTPException(
                status_code=400,
                detail=result.to_dict(),
            )
        return result.to_dict()

    @app.get("/catalog")
    def get_catalog():
        return logix.tools.format("json")

    @app.on_event("startup")
    async def startup():
        asyncio.create_task(background_worker())


if __name__ == "__main__":
    if not HAS_FASTAPI:
        print("This example requires fastapi and uvicorn.")
        print("Install with: pip install fastapi uvicorn")
        print("\nRunning the plan directly instead:")
        result = logix.run({"call": "add", "with": {"a": 1, "b": 2}})
        print(json.dumps(result.to_dict(), indent=2))
    else:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=8000)