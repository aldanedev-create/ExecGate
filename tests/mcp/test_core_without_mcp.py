"""
The core package works without FastMCP installed.

Unlike Pydantic, FastMCP is required by ``logiq_mcp``, not by ``logix``.
This test proves:

1. ``import logiq`` works with FastMCP uninstalled.
2. ``Logix()`` constructs and ``logix.run()`` executes.
3. ``import logiq_mcp`` raises a clear ImportError with the install hint.

Uses ``sys.modules['fastmcp'] = None`` in a subprocess to simulate the
absence without uninstalling.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_import_logix_without_fastmcp():
    r = _run("""
import sys
sys.modules['fastmcp'] = None
import logiq
assert logiq.__version__
print('ok')
""")
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


def test_engine_and_run_without_fastmcp():
    r = _run("""
import sys
sys.modules['fastmcp'] = None
from logiq import Logix

logix = Logix()

@logix.capability
def add(a: int, b: int) -> int:
    'Add.'
    return a + b

r = logix.run({'call': 'add', 'with': {'a': 1, 'b': 2}})
assert r.ok, r.errors
assert r.value == 3
print('ok')
""")
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


def test_multi_step_without_fastmcp():
    r = _run("""
import sys
sys.modules['fastmcp'] = None
from logiq import Logix

logix = Logix()

@logix.capability
def one() -> int:
    return 1

@logix.capability
def two(x: int) -> int:
    return x + 1

result = logix.run({
    'version': '1',
    'steps': [
        {'id': 'a', 'call': 'one', 'with': {}},
        {'id': 'b', 'call': 'two', 'with': {'x': {'$ref': 'a'}}},
    ],
})
assert result.ok, result.errors
assert result.value == {'a': 1, 'b': 2}
print('ok')
""")
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


def test_import_logix_mcp_raises_clear_error():
    r = _run("""
import sys
sys.modules['fastmcp'] = None
try:
    import logiq_mcp
    print('UNEXPECTED: import succeeded')
    sys.exit(1)
except ImportError as e:
    msg = str(e)
    assert 'fastmcp' in msg.lower(), f"'fastmcp' not in error: {msg!r}"
    assert 'logiq[mcp]' in msg, f"'logiq[mcp]' not in error: {msg!r}"
    print('ok')
""")
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout
    assert "UNEXPECTED" not in r.stdout