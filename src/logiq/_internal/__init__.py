"""
Internal utilities.

This package is **not** part of the public API. Names here may change
without a changelog entry. Import from ``logiq`` or the public modules
instead.

Two concerns:

- ``immutability`` — freezing, canonical hashing, tamper detection.
- ``redaction``    — stripping secrets and PII from diagnostics.
"""

from __future__ import annotations

from logiq._internal.immutability import (
    canonical_hash,
    canonical_json,
    freeze,
    is_frozen,
    thaw,
)
from logiq._internal.redaction import (
    DEFAULT_REDACTOR,
    REDACTED,
    Redactor,
    redact,
)

__all__ = [
    "DEFAULT_REDACTOR",
    "REDACTED",
    "Redactor",
    "canonical_hash",
    "canonical_json",
    "freeze",
    "is_frozen",
    "redact",
    "thaw",
]
