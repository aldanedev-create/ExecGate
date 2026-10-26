"""
No eval / exec / __import__ of model input.

Logix must never execute model-supplied data as code. The plan is JSON,
parsed with ``json.loads``, and access to its fields is dict access.
Capability dispatch is a registry lookup — never attribute access on
model-supplied names.

This test has two parts:

1. **Static AST scan.** The plan/execute path must not contain calls to
   ``eval``, ``exec``, or ``__import__``. This is the source-level
   guarantee.

2. **Runtime probes.** Malicious-looking plans are rejected as
   ``UNKNOWN_CAPABILITY``; nothing is evaluated.

Known, documented exception: ``schemas/infer.py::_resolve`` uses ``eval``
on *string annotations*, at *registration time*, against an
*application-controlled namespace*. That is not the plan-execution path
and is not covered by the AST scan below.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Static AST scan of the plan-execution path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC = _PROJECT_ROOT / "src" / "logiq"

# These modules form the trust-boundary pipeline for a plan. None of them
# may call eval/exec/__import__.
_SCANNED_FILES = [
    _SRC / "plans" / "parse.py",
    _SRC / "plans" / "format.py",
    _SRC / "plans" / "references.py",
    _SRC / "plans" / "limits.py",
    _SRC / "verifier.py",
    _SRC / "executor.py",
    _SRC / "engine.py",
    _SRC / "semantic" / "grounding.py",
    _SRC / "semantic" / "invariants.py",
    _SRC / "semantic" / "recheck.py",
    _SRC / "semantic" / "idempotency.py",
    _SRC / "semantic" / "repair_loop.py",
]

_FORBIDDEN = {"eval", "exec", "__import__"}


def _forbidden_calls(source: str, path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(source, filename=str(path))
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # Bare-name call: eval(...), exec(...), __import__(...)
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN:
                hits.append((node.lineno, func.id))
            # Attribute call: builtins.eval(...)
            elif isinstance(func, ast.Attribute) and func.attr in _FORBIDDEN:
                hits.append((node.lineno, func.attr))
    return hits


@pytest.mark.security
@pytest.mark.parametrize("path", _SCANNED_FILES, ids=[p.name for p in _SCANNED_FILES])
def test_no_eval_exec_import_in_plan_path(path: Path) -> None:
    assert path.exists(), f"missing expected source file: {path}"
    source = path.read_text(encoding="utf-8")
    hits = _forbidden_calls(source, path)
    assert hits == [], (
        f"{path.name} contains forbidden calls to "
        f"{[name for _, name in hits]} at lines "
        f"{[line for line, _ in hits]}. "
        f"Model input must never be evaluated as code."
    )


# ---------------------------------------------------------------------------
# Runtime probes
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_plan_naming_eval_is_rejected_as_unknown(logix):
    invoked = []

    @logix.capability
    def real_cap(x: int) -> int:
        invoked.append(1)
        return x

    # A plan that would trigger eval if Logix did that.
    result = logix.run(
        {
            "call": "eval",
            "with": {"x": "__import__('os').system('rm -rf /')"},
        }
    )
    assert not result.ok
    assert result.errors[0].code == "UNKNOWN_CAPABILITY"
    assert invoked == []


@pytest.mark.security
def test_plan_naming_dunder_import_is_rejected(logix):
    @logix.capability
    def real_cap(x: int) -> int:
        return x

    result = logix.run({"call": "__import__", "with": {"x": "os"}})
    assert not result.ok
    assert result.errors[0].code == "UNKNOWN_CAPABILITY"


@pytest.mark.security
def test_plan_naming_dunder_globals_is_rejected(logix):
    @logix.capability
    def real_cap(x: int) -> int:
        return x

    for name in ("__builtins__", "__globals__", "__dict__", "__class__"):
        result = logix.run({"call": name, "with": {}})
        assert not result.ok, f"{name} unexpectedly succeeded"
        assert result.errors[0].code == "UNKNOWN_CAPABILITY"


@pytest.mark.security
def test_string_argument_is_treated_as_data(logix):
    """Even hostile-looking strings arrive at the handler as inert data."""
    received = []

    @logix.capability
    def echo(x: str) -> str:
        received.append(x)
        return x

    hostile = "__import__('os').system('echo pwned')"
    result = logix.run({"call": "echo", "with": {"x": hostile}})
    assert result.ok
    assert result.value == hostile  # passed through unchanged, not evaluated
    assert received == [hostile]
