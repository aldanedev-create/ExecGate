"""
Optional Pydantic integration.

This package is an extra. Importing it without Pydantic installed raises
``ImportError`` — the standard semantics for an optional dependency.

The core ``logiq`` package never imports this module at import time. When
this package is importable, ``execgate.capabilities`` auto-detects it and
enables Pydantic handling for capability registration. ``install(logiq)``
is an explicit assertion that this should work; it exists for startup-time
self-checks, not for enabling behaviour.

See ``docs/pydantic.md``.
"""

from __future__ import annotations

try:
    import pydantic
except ImportError as e:  # pragma: no cover — tested via test_core_without_pydantic
    raise ImportError(
        'execgate_pydantic requires pydantic; install with: pip install "logiq[pydantic]"'
    ) from e

if int(pydantic.VERSION.split(".", 1)[0]) != 2:
    raise ImportError(f"execgate_pydantic requires pydantic>=2,<3; got {pydantic.VERSION}")

from execgate_pydantic.adapter import (
    HAS_PYDANTIC,
    PydanticAdapter,
    is_pydantic_model,
    normalize_validation_error,
    transform_signature,
)
from execgate_pydantic.handler_mode import (
    HandlerMode,
    get_handler_mode,
    install,
    set_handler_mode,
)
from execgate_pydantic.schema_bridge import (
    PydanticType,
    model_to_json_schema,
    model_to_logix_type,
)

__all__ = [
    "HAS_PYDANTIC",
    "HandlerMode",
    "PydanticAdapter",
    "PydanticType",
    "get_handler_mode",
    "install",
    "is_pydantic_model",
    "model_to_json_schema",
    "model_to_logix_type",
    "normalize_validation_error",
    "set_handler_mode",
    "transform_signature",
]
