"""
HandlerMode: what the handler receives for Pydantic-typed parameters.

Two modes:

- ``MODEL``  (default): handler receives a model instance.
- ``VALUES``: handler receives ``model_dump(mode="json")`` — plain JSON
  values, matching what arrived in the plan.

The mode is a global in 0.1.0. Tests save and restore it around each
test so ordering does not matter, except for the "default is MODEL"
test which runs in a subprocess to observe the pristine default.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from pydantic import BaseModel

from logix_pydantic import (
    HandlerMode,
    get_handler_mode,
    install,
    set_handler_mode,
)


# ---------------------------------------------------------------------------
# Reset global around every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _restore_handler_mode():
    original = get_handler_mode()
    yield
    set_handler_mode(original)


# ---------------------------------------------------------------------------
# Enum surface
# ---------------------------------------------------------------------------

def test_handler_mode_enum_values():
    assert HandlerMode.MODEL.value == "model"
    assert HandlerMode.VALUES.value == "values"


def test_default_is_model_in_subprocess():
    """The module-level default is MODEL. Observed in a fresh interpreter
    so prior tests cannot have mutated it."""
    code = """
from logix_pydantic import get_handler_mode, HandlerMode
assert get_handler_mode() == HandlerMode.MODEL
print('ok')
"""
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


# ---------------------------------------------------------------------------
# set_handler_mode / get_handler_mode
# ---------------------------------------------------------------------------

def test_set_mode_with_enum():
    set_handler_mode(HandlerMode.VALUES)
    assert get_handler_mode() == HandlerMode.VALUES

    set_handler_mode(HandlerMode.MODEL)
    assert get_handler_mode() == HandlerMode.MODEL


def test_set_mode_with_string():
    set_handler_mode("values")
    assert get_handler_mode() == HandlerMode.VALUES

    set_handler_mode("model")
    assert get_handler_mode() == HandlerMode.MODEL


def test_set_mode_invalid_string():
    with pytest.raises(ValueError, match="'model' or 'values'"):
        set_handler_mode("invalid")


# ---------------------------------------------------------------------------
# install() is a no-op assertion
# ---------------------------------------------------------------------------

def test_install_does_not_raise(logix):
    install(logix)  # must not raise


# ---------------------------------------------------------------------------
# End-to-end: MODEL mode
# ---------------------------------------------------------------------------

def test_model_mode_handler_receives_model_instance(logix):
    class Item(BaseModel):
        x: int
        y: str

    received: list[Item] = []

    @logix.capability
    def op(item: Item) -> dict[str, int]:
        received.append(item)
        return {"ok": 1}

    set_handler_mode(HandlerMode.MODEL)
    result = logix.run({"call": "op", "with": {"item": {"x": 42, "y": "hi"}}})

    assert result.ok
    assert len(received) == 1
    assert isinstance(received[0], Item)
    assert received[0].x == 42
    assert received[0].y == "hi"


# ---------------------------------------------------------------------------
# End-to-end: VALUES mode
# ---------------------------------------------------------------------------

def test_values_mode_handler_receives_dict(logix):
    class Item(BaseModel):
        x: int
        y: str

    received: list[dict] = []

    @logix.capability
    def op(item: Item) -> dict[str, int]:
        received.append(item)  # type: ignore[arg-type]
        return {"ok": 1}

    set_handler_mode(HandlerMode.VALUES)
    result = logix.run({"call": "op", "with": {"item": {"x": 42, "y": "hi"}}})

    assert result.ok
    assert len(received) == 1
    assert isinstance(received[0], dict)
    assert received[0] == {"x": 42, "y": "hi"}


# ---------------------------------------------------------------------------
# Validation runs before either mode conversion
# ---------------------------------------------------------------------------

def test_validation_runs_before_handler_in_either_mode(logix):
    class Item(BaseModel):
        x: int

    for mode in (HandlerMode.MODEL, HandlerMode.VALUES):
        set_handler_mode(mode)
        invoked: list[int] = []

        @logix.capability(name=f"op_{mode.value}")
        def op(item: Item) -> dict[str, int]:
            invoked.append(1)
            return {"ok": 1}

        result = logix.run({
            "call": f"op_{mode.value}",
            "with": {"item": {"x": "not-an-int"}},
        })
        assert not result.ok
        assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"
        assert invoked == [], f"handler ran in {mode.value} mode with bad input"


# ---------------------------------------------------------------------------
# Nested models under VALUES mode
# ---------------------------------------------------------------------------

def test_values_mode_recursively_flattens(logix):
    class Address(BaseModel):
        city: str

    class Order(BaseModel):
        id: int
        address: Address

    received: list[dict] = []

    @logix.capability
    def op(order: Order) -> dict[str, int]:
        received.append(order)  # type: ignore[arg-type]
        return {"ok": 1}

    set_handler_mode(HandlerMode.VALUES)
    result = logix.run({
        "call": "op",
        "with": {"order": {"id": 1, "address": {"city": "Berlin"}}},
    })

    assert result.ok
    assert received[0] == {"id": 1, "address": {"city": "Berlin"}}