"""
Shared fixtures and helpers for the adapter conformance kit.

The contract mixin provides its own sample data as module constants.
This conftest exists to anchor pytest discovery for the package and to
declare the ``conformance`` marker convention used by every test in this
directory.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-tag every test in this package with ``conformance``."""
    for item in items:
        if "/adapters/" in str(item.fspath):
            item.add_marker(pytest.mark.conformance)
