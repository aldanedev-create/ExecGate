"""
Approval tokens.

An approval token is the application's assertion that a specific human or
system authorized a specific action with specific arguments, for a
specific principal, in a specific context. The model cannot construct or
forge one because approval is not part of the AI's output channel.

A token is validated in the recheck window before a protected handler
runs. Any mismatch in capability, args, principal, or context invalidates
the token and yields ``APPROVAL_REQUIRED``.

See ``docs/system-design.md §5`` and ADR-0004.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from logiq.context import ExecutionContext


__all__ = [
    "ApprovalToken",
    "canonical_args_hash",
    "context_hash",
    "issue",
]


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def canonical_args_hash(args: dict[str, Any]) -> str:
    """
    Deterministic hash of a resolved argument map.

    Two calls with the same arguments in any insertion order produce the
    same digest. Used to bind a token to the exact action.
    """
    payload = json.dumps(
        args,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def context_hash(context: ExecutionContext) -> str:
    """
    Deterministic hash of the relevant parts of a context.

    Excludes ``request_id`` and ``extra`` — a token bound to the principal,
    tenant, and roles should remain valid across a change of request id,
    and ``extra`` is application-defined metadata whose stability we
    cannot assume.
    """
    payload = {
        "principal": context.principal,
        "tenant": context.tenant,
        "roles": sorted(context.roles),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# ApprovalToken
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalToken:
    """
    An opaque assertion of approval bound to a specific action.

    Constructed only by ``logiq.approval.issue(...)`` (application side).
    The AI never sees this object and cannot produce one. Because it is
    frozen and its fields are all primitives, a token is either *the one
    issued for this exact action* or it is not — there is no partial
    match.
    """

    capability: str
    args_hash: str
    principal: str
    context_hash: str
    issued_at: float
    issuer: str

    def matches(
        self,
        capability: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> bool:
        """
        True iff the token binds to exactly this action.

        Checks capability, args, principal, and context. Does not check
        expiry — 0.1.0 tokens do not expire; the application is
        responsible for issuing tokens with a bounded lifetime if it
        needs one (e.g. by not storing them past a threshold).
        """
        return (
            self.capability == capability
            and self.args_hash == canonical_args_hash(args)
            and self.principal == context.principal
            and self.context_hash == context_hash(context)
        )

    def to_dict(self) -> dict[str, Any]:
        """Safe serialization for audit. Contains no secrets by design."""
        return {
            "capability": self.capability,
            "args_hash": self.args_hash,
            "principal": self.principal,
            "context_hash": self.context_hash,
            "issued_at": self.issued_at,
            "issuer": self.issuer,
        }


# ---------------------------------------------------------------------------
# Issuance
# ---------------------------------------------------------------------------


def issue(
    *,
    capability: str,
    args: dict[str, Any],
    context: ExecutionContext,
    issuer: str,
) -> ApprovalToken:
    """
    Application-side issuance.

    Must be called only from a trusted code path (an approval UI callback,
    an admin tool, an upstream system that has already decided to grant
    approval). The AI has no path to this function: it does not exist in
    any adapter, and the AI does not receive an ``ApprovalToken``.

    Parameters
    ----------
    capability
        Public capability name (e.g. ``"issue_refund"``).
    args
        The exact argument map the approval is for. Must match the args
        that will be passed at execution time; otherwise the token will
        not ``matches()``.
    context
        The trusted execution context for the call.
    issuer
        Identifier of the approver (e.g. ``"human:alice"``,
        ``"system:billing"``). For audit only; not validated by Logix.

    Raises
    ------
    ValueError
        If ``capability`` or ``issuer`` is empty, or ``args`` is not a
        mapping.
    """
    if not isinstance(capability, str) or not capability:
        raise ValueError("capability must be a non-empty string")
    if not isinstance(args, dict):
        raise TypeError(f"args must be a dict; got {type(args).__name__}")
    if not isinstance(issuer, str) or not issuer:
        raise ValueError("issuer must be a non-empty string")

    return ApprovalToken(
        capability=capability,
        args_hash=canonical_args_hash(args),
        principal=context.principal,
        context_hash=context_hash(context),
        issued_at=time.time(),
        issuer=issuer,
    )
