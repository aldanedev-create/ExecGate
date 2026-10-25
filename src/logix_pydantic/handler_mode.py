"""
Handler input mode.

Two modes:

- ``MODEL``  — the handler receives a Pydantic model instance for each
  parameter whose type is a Pydantic model.
- ``VALUES`` — the handler receives the model's ``model_dump(mode="json")``,
  i.e. plain JSON-safe data.

The mode is **global** in 0.1.0 and applies to every capability on every
engine. It is a deployment choice, not a per-call option. A later version
may allow per-capability override via decorator options.

Changing the mode at runtime affects subsequent executions only; it does
not mutate capability registrations. Reads are not synchronized with
writes in 0.1.0 — configure the mode at application startup.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logix.engine import Logix


class HandlerMode(str, Enum):
    """What the handler receives for parameters typed as Pydantic models."""

    MODEL = "model"      # Pydantic model instance
    VALUES = "values"    # plain dict (model_dump(mode="json"))


_default_mode: HandlerMode = HandlerMode.MODEL


def get_handler_mode() -> HandlerMode:
    """Return the current global handler mode."""
    return _default_mode


def set_handler_mode(mode: "HandlerMode | str") -> HandlerMode:
    """
    Set the global handler mode. Returns the new mode.

    Accepts ``HandlerMode`` or its string value (``"model"`` / ``"values"``).
    Raises ``ValueError`` on an unknown value.
    """
    global _default_mode
    if isinstance(mode, str):
        try:
            mode = HandlerMode(mode)
        except ValueError as e:
            raise ValueError(
                f"handler_mode must be 'model' or 'values', got {mode!r}"
            ) from e
    _default_mode = mode
    return _default_mode


def install(logix: "Logix") -> None:
    """
    Explicitly enable the Pydantic adapter on ``logix``.

    This is an *assertion*, not an enabler: if Pydantic is importable,
    auto-detection already works, and this function is a no-op that raises
    if something is broken. Call it at application startup to fail fast
    when the ``[pydantic]`` extra was expected but not installed.

    The ``logix`` argument is accepted for forward compatibility (per-engine
    configuration); 0.1.0 has no per-engine flag.
    """
    # Import is at module load; if we're here, pydantic is available.
    # The only failure mode is a version mismatch that __init__.py already
    # rejected, so nothing else to check.
    _ = logix  # per-engine install location reserved