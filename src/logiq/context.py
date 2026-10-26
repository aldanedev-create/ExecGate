"""
Trusted execution context.

``ExecutionContext`` carries the identity and authorization information
supplied by the *application* — never by the AI. It flows through
``run()``, ``verify()``, ``execute()``, and the recheck window.

Identity here is *declared* by the application. It is not proof of
authorization; that is the job of ``logiq.authorize(...)`` checks and the
recheck window (see ``docs/system-design.md §5``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class ExecutionContext:
    """
    Identity and request metadata for one call.

    ``principal`` is the application's identifier for the caller — a user
    ID, service account, or tenant. ``roles`` are the roles the
    application has already authenticated. ``extra`` is a free-form map
    the application can use for domain-specific data (e.g. tenant
    entitlements), but **must not** be populated from AI output.
    """

    principal: str
    tenant: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    request_id: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.principal, str) or not self.principal:
            raise ValueError("principal must be a non-empty string")
        # Freeze the extra map so it cannot be mutated between verify and
        # execute. The recheck window re-reads the *current* context, but
        # a single ExecutionContext object is immutable.
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))
        if not isinstance(self.roles, frozenset):
            object.__setattr__(self, "roles", frozenset(self.roles))

    def with_roles(self, *roles: str) -> "ExecutionContext":
        """Return a copy with additional roles (for tests and fixtures)."""
        return ExecutionContext(
            principal=self.principal,
            tenant=self.tenant,
            roles=self.roles | frozenset(roles),
            request_id=self.request_id,
            extra=dict(self.extra),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "principal": self.principal,
            "tenant": self.tenant,
            "roles": sorted(self.roles),
            "request_id": self.request_id,
            "extra": dict(self.extra),
        }