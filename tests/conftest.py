"""
Shared fixtures.

Tests are intentionally light on fixtures — most build their own
``Logix`` engine or ``Registry`` so failures are localized. The
``logix`` fixture exists for tests that just need *a* fresh engine.
"""

from __future__ import annotations

import pytest

from logiq import Logix
from logiq.context import ExecutionContext


@pytest.fixture
def logix() -> Logix:
    """A fresh, empty engine."""
    return Logix()


@pytest.fixture
def ctx() -> ExecutionContext:
    """A minimal trusted context for tests that pass one explicitly."""
    return ExecutionContext(principal="test-user")