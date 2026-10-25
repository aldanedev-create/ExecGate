"""
Internal utilities.

This package is **not** part of the public API. Names here may change
without a changelog entry. Import from ``logix`` or the public modules
instead.

Two concerns:

- ``immutability`` — freezing, canonical hashing, tamper detection.
- ``redaction``    — stripping secrets and PII from diagnostics.
"""

from __future__ import annotations

from logix._internal.immutability import (
    canonical_hash, canonical_json, freeze, is_frozen, thaw,
)
from logix._internal.redaction import (
    REDACTED, Redactor, DEFAULT_REDACTOR, redact,
)

__all__ = [
    "canonical_hash", "canonical_json", "freeze", "is_frozen", "thaw",
    "REDACTED", "Redactor", "DEFAULT_REDACTOR", "redact",
]