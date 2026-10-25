"""
Diagnostics redaction.

Every value that leaves Logix through a diagnostic channel — ``Result.to_dict``,
``Trace``, error ``details``, an audit event — passes through this module
first. By default it removes:

- values keyed by a sensitive name (``password``, ``token``, ``authorization``,
  ``credit_card``, ``ssn``, and similar), and
- values at any path the caller marked sensitive.

Redaction never changes the *shape* of a structure. A dict with a redacted
field still has that field; its value is replaced with the sentinel. That
way callers and clients see a stable schema whether or not a field was
redacted.

**What this module deliberately does not do by default:**

- Pattern-based matching (emails, phone numbers, SSNs, credit card numbers
  embedded in free text). Some applications want it; none should get it by
  accident. Opt in via ``Redactor(patterns=...)``.
- Regex over free-form strings. Same reason.
- Redact argument values from the trace. The trace should not contain raw
  argument values in the first place (see ``observability.py``); this
  module is a last line of defense, not the primary strategy.

See ``docs/system-design.md §8``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Pattern


REDACTED = "[REDACTED]"


# Names whose *values* are sensitive regardless of path. Case-insensitive by
# default. Names are matched exactly against dict keys; use paths for
# targeted redaction in nested structures.
DEFAULT_SENSITIVE_KEYS: frozenset[str] = frozenset({
    # auth
    "password", "passwd", "pwd",
    "token", "access_token", "refresh_token", "id_token",
    "api_key", "apikey", "secret", "client_secret",
    "authorization", "auth_header",
    "session", "session_key", "session_id",
    "private_key", "signing_key",
    # pii
    "credit_card", "card_number", "cvv", "cvc",
    "ssn", "social_security_number",
    "date_of_birth", "dob",
    # internal
    "secret_key", "encryption_key",
})


@dataclass(frozen=True)
class Redactor:
    """
    A redaction policy.

    Two mechanisms, applied independently:

    - ``sensitive_keys``     — matched against dict keys (case-insensitive
                               by default). Any field with a matching name
                               is redacted regardless of path.
    - ``redact_paths``       — dotted paths into the value, e.g.
                               ``"arguments.customer.password"``. Use when
                               a key name is not sensitive in general but
                               is in a specific place.
    - ``patterns``           — optional regex patterns applied to string
                               values. Off by default; opt-in for PII-in-text.
    """

    sensitive_keys: frozenset[str] = DEFAULT_SENSITIVE_KEYS
    redact_paths: frozenset[str] = frozenset()
    case_insensitive: bool = True
    replacement: str = REDACTED
    patterns: tuple["Pattern[str]", ...] = ()

    _lower_keys: frozenset[str] = field(default=None, init=False, repr=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.case_insensitive:
            object.__setattr__(
                self, "_lower_keys",
                frozenset(k.lower() for k in self.sensitive_keys),
            )
        else:
            object.__setattr__(self, "_lower_keys", self.sensitive_keys)
        # Normalize paths to a frozenset of non-empty strings.
        normalized_paths = frozenset(p for p in self.redact_paths if p)
        object.__setattr__(self, "redact_paths", normalized_paths)

    def should_redact_key(self, key: str) -> bool:
        if self.case_insensitive:
            return key.lower() in self._lower_keys
        return key in self._lower_keys

    def should_redact_path(self, path: str) -> bool:
        return path in self.redact_paths


# The default singleton. Frozen, so safe to share.
DEFAULT_REDACTOR = Redactor()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def redact(
    value: Any,
    redactor: "Redactor | None" = None,
    *,
    path: str = "",
) -> Any:
    """
    Return a redacted copy of ``value``.

    Preserves the structure: dicts stay dicts, lists stay lists, scalars
    stay scalars. Only the *values* of matching keys (or keys at matching
    paths) become ``replacement``.

    Never mutates the input. If ``value`` is already frozen, the result is
    a mutable copy (because ``to_dict`` is meant to hand out plain data).
    """
    r = redactor or DEFAULT_REDACTOR

    if isinstance(value, (MappingProxyType, Mapping)):
        return _redact_mapping(value, r, path)
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        return [
            _redact_value(v, r, f"{path}[{i}]")
            for i, v in enumerate(items)
        ]
    return _redact_value(value, r, path)


def _redact_mapping(
    value: Mapping[Any, Any],
    redactor: Redactor,
    path: str,
) -> dict[Any, Any]:
    out: dict[Any, Any] = {}
    for k, v in value.items():
        child_path = f"{path}.{k}" if path else str(k)
        if isinstance(k, str) and (
            redactor.should_redact_key(k)
            or redactor.should_redact_path(child_path)
        ):
            out[k] = redactor.replacement
        else:
            out[k] = _redact_value(v, redactor, child_path)
    return out


def _redact_value(value: Any, redactor: Redactor, path: str) -> Any:
    if isinstance(value, (MappingProxyType, Mapping)):
        return _redact_mapping(value, redactor, path)
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        return [
            _redact_value(v, redactor, f"{path}[{i}]")
            for i, v in enumerate(items)
        ]
    if isinstance(value, str) and redactor.patterns:
        for pattern in redactor.patterns:
            value = pattern.sub(redactor.replacement, value)
    return value


# ---------------------------------------------------------------------------
# Convenience for error details
# ---------------------------------------------------------------------------

def redact_details(
    details: Mapping[str, Any],
    redactor: "Redactor | None" = None,
) -> dict[str, Any]:
    """
    Redact an error ``details`` map before it goes into a public error.

    Wrapped as a named function so error constructors can call it with an
    obvious intent, and so tests can assert on it directly.
    """
    result = redact(details, redactor)
    # Guaranteed to be a dict because ``details`` is a mapping.
    assert isinstance(result, dict)
    return result