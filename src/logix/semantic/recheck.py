"""
The recheck window.

Runs before every handler invocation inside ``executor.execute_verified``.
This is where every check that depends on live state lives:

1. Context refresh — the application may supply a refresher; if the
   principal changed, deny.
2. Invariants     — the ``logix.authorize(check=...)`` callback.
3. Approval       — the token must match capability + args + principal +
                    context. Mismatch = APPROVAL_REQUIRED.
4. Idempotency    — reserve / replay / conflict.

The recheck window is the only place live state is read. See
``docs/system-design.md §5``.

Verification is not an authorization grant (ADR-0004): the recheck window
re-earns the dynamic guarantees on every step, every execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from logix.errors import (
    Error, approval_required, authorization_failed, idempotency_conflict,
)
from logix.policies import Allow, Deny, RequireApproval

from logix.semantic.idempotency import (
    IdempotencyResult, IdempotencyStatus, IdempotencyStore,
)
from logix.semantic.invariants import (
    InvariantRegistry, decision_to_error, run_invariants,
)

if TYPE_CHECKING:
    from logix.approval import ApprovalToken
    from logix.context import ExecutionContext


class RecheckStatus(str, Enum):
    PROCEED = "proceed"
    REPLAY = "replay"                    # cached result available
    DENY = "deny"                        # rejected; do not invoke
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True)
class RecheckResult:
    status: RecheckStatus
    error: Error | None = None
    cached_value: Any = None


def recheck_step(
    *,
    capability: str,
    args: dict[str, Any],
    context: "ExecutionContext",
    invariants: InvariantRegistry,
    approval_token: "ApprovalToken | None" = None,
    approval_required_flag: bool = False,
    idempotency_store: "IdempotencyStore | None" = None,
    idempotency_key: str | None = None,
    idempotency_args_hash: str | None = None,
    context_refresher: "Callable[[], ExecutionContext] | None" = None,
) -> RecheckResult:
    """
    Run every dynamic check before a step's handler is invoked.

    Called by the executor once per step. Returns a ``RecheckResult``
    indicating whether the executor should proceed, return a cached value,
    deny, or escalate to approval.

    Every failure mode returns a structured ``RecheckResult``; this
    function never raises.
    """
    # 1. Context refresh (optional).
    if context_refresher is not None:
        try:
            refreshed = context_refresher()
        except Exception as e:
            return RecheckResult(
                RecheckStatus.DENY,
                authorization_failed(
                    f"context refresh failed: {type(e).__name__}",
                ),
            )
        if refreshed.principal != context.principal:
            return RecheckResult(
                RecheckStatus.DENY,
                authorization_failed(
                    "principal changed between verify and execute",
                ),
            )
        # Re-run checks against the refreshed context.
        context = refreshed

    # 2. Invariants.
    decision, error = run_invariants(invariants, capability, args, context)
    if error is not None:
        return RecheckResult(RecheckStatus.DENY, error)
    if isinstance(decision, Deny):
        return RecheckResult(
            RecheckStatus.DENY,
            decision_to_error(decision),
        )
    if isinstance(decision, RequireApproval):
        # Fall through to the approval check.
        approval_required_flag = True

    # 3. Approval.
    if approval_required_flag:
        if approval_token is None:
            return RecheckResult(
                RecheckStatus.APPROVAL_REQUIRED,
                approval_required(capability),
            )
        if not approval_token.matches(capability, args, context):
            return RecheckResult(
                RecheckStatus.APPROVAL_REQUIRED,
                approval_required(capability),
            )

    # 4. Idempotency (only if a key was supplied).
    if idempotency_store is not None and idempotency_key is not None:
        if idempotency_args_hash is None:
            return RecheckResult(
                RecheckStatus.DENY,
                authorization_failed(
                    "idempotency_key supplied without args_hash",
                ),
            )
        idem = idempotency_store.check_and_reserve(
            idempotency_key, idempotency_args_hash,
        )
        if idem.status is IdempotencyStatus.CONFLICT:
            return RecheckResult(
                RecheckStatus.DENY,
                idempotency_conflict(idempotency_key),
            )
        if idem.status is IdempotencyStatus.REPLAY:
            return RecheckResult(
                RecheckStatus.REPLAY,
                cached_value=idem.cached_value,
            )
        # RESERVED: proceed; the executor commits after handler success.

    return RecheckResult(RecheckStatus.PROCEED)