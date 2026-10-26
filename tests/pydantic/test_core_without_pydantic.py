"""
The core has zero third-party runtime dependencies.

Even without Pydantic installed, ``import execgate`` works, ``Logix()``
constructs, and non-Pydantic capabilities register and run. Attempting
to import ``execgate_pydantic`` raises a clear ``ImportError`` telling the
user how to install the extra.

Because Pydantic is installed in the test environment, each
"without-Pydantic" scenario runs in a subprocess with
``sys.modules['pydantic'] = None`` — the standard way to simulate a
missing module without uninstalling it.
"""

from __future__ import annotations

import subprocess
import sys


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Core works without Pydantic
# ---------------------------------------------------------------------------


def test_import_logix_without_pydantic():
    code = """
import sys
sys.modules['pydantic'] = None
import execgate
assert execgate.__version__
print('ok')
"""
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


def test_engine_constructs_without_pydantic():
    code = """
import sys
sys.modules['pydantic'] = None
from execgate import Logix
logix = Logix()
assert logix.registry.names() == []
print('ok')
"""
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


def test_register_and_run_without_pydantic():
    code = """
import sys
sys.modules['pydantic'] = None
from execgate import Logix

logix = Logix()

@logix.capability
def add(a: int, b: int) -> int:
    'Add.'
    return a + b

r = logix.run({'call': 'add', 'with': {'a': 1, 'b': 2}})
assert r.ok, r.errors
assert r.value == 3
print('ok')
"""
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


def test_multi_step_without_pydantic():
    code = """
import sys
sys.modules['pydantic'] = None
from execgate import Logix

logix = Logix()

@logix.capability
def one() -> int:
    return 1

@logix.capability
def two(x: int) -> int:
    return x + 1

r = logix.run({
    'version': '1',
    'steps': [
        {'id': 'a', 'call': 'one', 'with': {}},
        {'id': 'b', 'call': 'two', 'with': {'x': {'$ref': 'a'}}},
    ],
})
assert r.ok, r.errors
assert r.value == {'a': 1, 'b': 2}
print('ok')
"""
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


# ---------------------------------------------------------------------------
# Importing execgate_pydantic raises a clear error
# ---------------------------------------------------------------------------


def test_import_logix_pydantic_raises_clear_error():
    code = """
import sys
sys.modules['pydantic'] = None
try:
    import execgate_pydantic
    print('UNEXPECTED: import succeeded')
    sys.exit(1)
except ImportError as e:
    msg = str(e)
    assert 'pydantic' in msg.lower()
    assert 'logiq[pydantic]' in msg
    print('ok')
"""
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout
    assert "UNEXPECTED" not in r.stdout


# ---------------------------------------------------------------------------
# In-process: core behaviors work fine regardless of pydantic availability
# ---------------------------------------------------------------------------


def test_non_model_capability_works_in_process(logix):
    """Sanity — the non-Pydantic path works in the normal test process."""

    @logix.capability
    def add(a: int, b: int) -> int:
        return a + b

    r = logix.run({"call": "add", "with": {"a": 1, "b": 2}})
    assert r.ok
    assert r.value == 3
