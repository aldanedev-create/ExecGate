"""
The semantic layer.

The core verifies that a plan is *well-formed and statically permitted*.
The semantic layer reduces the residual risk that a well-formed plan is
*semantically wrong* — the class of failure the core explicitly does not
claim to eliminate (see ``docs/system-design.md`` and ``docs/usage-model.md``).

Five concerns, each opt-in:

- **Grounding** (``grounding``)       — sensitive args must come from a
  ``$ref`` or an allowlisted literal, never model-typed values.
- **Invariants** (``invariants``)     — live-state authorize checks attached
  per capability; the ``execgate.authorize(check=...)`` mechanism.
- **Recheck** (``recheck``)           — the per-step window that runs
  context refresh, invariants, approval, and idempotency before each
  handler invocation. Called by the executor.
- **Repair loop** (``repair_loop``)   — bounds the number of retries the
  application runs, and refuses attempts that treat a policy rejection as
  permission to reroute.
- **Idempotency** (``idempotency``)   — per-key deduplication of side
  effects. Best-effort in-core; a durable store is the application's job.

The semantic layer is **stdlib-only** and part of the core package. It is
not an optional adapter: the guarantees it provides are part of what makes
"Logix reduces hallucinations" a credible claim.
"""

from __future__ import annotations

from execgate.semantic.grounding import (
    GroundingPolicy,
    check_grounding,
)
from execgate.semantic.idempotency import (
    IdempotencyResult,
    IdempotencyStatus,
    IdempotencyStore,
    InMemoryIdempotencyStore,
)
from execgate.semantic.invariants import (
    InvariantRegistry,
    run_invariants,
)
from execgate.semantic.recheck import (
    RecheckResult,
    RecheckStatus,
    recheck_step,
)
from execgate.semantic.repair_loop import (
    RepairLoop,
    RepairRefused,
    RepairState,
)

__all__ = [
    "GroundingPolicy",
    "IdempotencyResult",
    "IdempotencyStatus",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "InvariantRegistry",
    "RecheckResult",
    "RecheckStatus",
    "RepairLoop",
    "RepairRefused",
    "RepairState",
    "check_grounding",
    "recheck_step",
    "run_invariants",
]
