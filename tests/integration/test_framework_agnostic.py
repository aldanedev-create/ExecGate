"""
The core is framework-agnostic.

Two claims:

1. **No core dependency on any web framework.** No module in
   ``src/logiq`` imports Flask, Django, FastAPI, Starlette, Pyramid,
   Bottle, Tornado, Sanic, or similar. This is enforced by an AST scan.

2. **Logix works without any framework context.** No app object, no
   request context, no global state. Multiple engines are isolated.
   Logix runs from module-level code, from class methods, from async
   contexts.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from logiq import Logix

# ---------------------------------------------------------------------------
# Static: no framework imports under src/logiq
# ---------------------------------------------------------------------------

_FRAMEWORKS = {
    "flask",
    "django",
    "fastapi",
    "starlette",
    "aiohttp",
    "pyramid",
    "bottle",
    "tornado",
    "sanic",
    "quart",
    "falcon",
    "litestar",
    "blacksheep",
    "cherrypy",
    "hug",
}

_SRC_LOGIX = Path(__file__).resolve().parents[2] / "src" / "logix"


def _imports_in_file(path: Path) -> set[str]:
    """Return the set of top-level module names imported by a Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
            # ``from . import x`` has module=None; skip.
    return names


def test_no_web_framework_imports_in_core():
    """No source file under ``src/logiq`` imports a web framework."""
    offenders: list[tuple[str, set[str]]] = []
    for path in _SRC_LOGIX.rglob("*.py"):
        imported = _imports_in_file(path)
        hits = imported & _FRAMEWORKS
        if hits:
            offenders.append((str(path.relative_to(_SRC_LOGIX)), hits))

    assert offenders == [], (
        f"src/logiq/ imports web frameworks in: {offenders}. "
        f"The core must be framework-agnostic (docs/usage-model.md)."
    )


# ---------------------------------------------------------------------------
# Runtime: import logiq with frameworks blocked
# ---------------------------------------------------------------------------


def _run_with_blocked_frameworks(code: str) -> subprocess.CompletedProcess[str]:
    # Block each framework by setting sys.modules['<name>'] = None BEFORE
    # the import. If logix tried to import one, Python raises ImportError.
    block = "\n".join(f"sys.modules[{name!r}] = None" for name in sorted(_FRAMEWORKS))
    full = f"import sys\n{block}\n{code}"
    return subprocess.run(
        [sys.executable, "-c", full],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_import_logix_with_frameworks_blocked():
    r = _run_with_blocked_frameworks("import logiq\nprint('ok')")
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


def test_run_capability_with_frameworks_blocked():
    r = _run_with_blocked_frameworks("""
from logiq import Logix
logix = Logix()

@logix.capability
def add(a: int, b: int) -> int:
    return a + b

result = logix.run({'call': 'add', 'with': {'a': 3, 'b': 4}})
assert result.ok, result.errors
assert result.value == 7
print('ok')
""")
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


# ---------------------------------------------------------------------------
# No framework context required
# ---------------------------------------------------------------------------


def test_engine_at_module_level():
    """A Logix engine can be constructed and used from module-level code,
    with no app, no request, no application-server context."""
    logix = Logix()

    @logix.capability
    def hello(name: str) -> str:
        return f"hello, {name}"

    assert logix.run({"call": "hello", "with": {"name": "world"}}).value == "hello, world"


def test_engine_inside_class_method():
    """A Logix engine can be used from inside a plain class method — no
    dependency-injection framework, no request scope."""

    class Service:
        def __init__(self):
            self.logix = Logix()

            @self.logix.capability
            def compute(x: int) -> int:
                return x * 2

        def run(self, x: int) -> int:
            result = self.logix.run({"call": "compute", "with": {"x": x}})
            assert result.ok
            return result.value

    service = Service()
    assert service.run(5) == 10
    assert service.run(3) == 6


@pytest.mark.asyncio
async def test_engine_inside_async_function():
    """No async requirement, but Logix works from inside an async context
    without interfering with the event loop."""

    logix = Logix()

    @logix.capability
    def compute(x: int) -> int:
        return x + 1

    async def caller():
        # Sync call inside async — fine; Logix is not async itself.
        result = logix.run({"call": "compute", "with": {"x": 5}})
        assert result.ok
        return result.value

    assert await caller() == 6


# ---------------------------------------------------------------------------
# Multiple engines are isolated
# ---------------------------------------------------------------------------


def test_multiple_engines_are_isolated():
    a = Logix()
    b = Logix()

    @a.capability
    def only_in_a(x: int) -> int:
        return x

    # a has the capability, b does not.
    assert "only_in_a" in a.registry
    assert "only_in_a" not in b.registry

    # b's run rejects it as unknown.
    result = b.run({"call": "only_in_a", "with": {"x": 1}})
    assert not result.ok
    assert result.errors[0].code == "UNKNOWN_CAPABILITY"


def test_engine_isolation_of_policies():
    """A policy attached to one engine does not affect another."""
    a = Logix()
    b = Logix()

    @a.capability
    def op(x: int) -> int:
        return x

    @b.capability
    def op(x: int) -> int:  # noqa: F811
        return x

    from logiq import Deny

    a.authorize(op, check=lambda args, ctx: Deny("A_BLOCKED", "no"))

    # a's op is blocked, b's is fine.
    assert not a.run({"call": "op", "with": {"x": 1}}).ok
    assert b.run({"call": "op", "with": {"x": 1}}).ok


# ---------------------------------------------------------------------------
# No global state
# ---------------------------------------------------------------------------


def test_creating_engine_does_not_affect_existing_engine():
    """Two engines created in sequence — the second doesn't reset the first."""
    a = Logix()

    @a.capability
    def cap_in_a(x: int) -> int:
        return x

    # Create another engine — a's state is untouched.
    _ = Logix()
    assert "cap_in_a" in a.registry
    assert a.run({"call": "cap_in_a", "with": {"x": 5}}).value == 5
