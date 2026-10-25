"""
``logix_mcp`` is a leaf node (ADR-0006, ADR-0007).

The package must not import from the trust-boundary internals:
``logix.verifier``, ``logix.executor``, ``logix.ir``, or
``logix._internal``.

If these imports ever appear, the package could bypass verification. The
structural guarantee is that the only way to run a handler from
``logix_mcp`` is via ``logix.run()`` or ``logix.execute(verified_plan)``,
both of which go through the full pipeline.

This test scans the source for those imports and for direct calls to the
bypass functions ``_construct_verified_plan`` and ``execute_verified``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


_LOGIX_MCP = Path(__file__).resolve().parents[2] / "src" / "logix_mcp"

_FORBIDDEN_MODULES = {
    "logix.verifier",
    "logix.executor",
    "logix.ir",
    "logix._internal",
}

_FORBIDDEN_FUNCTION_NAMES = {
    "_construct_verified_plan",
    "execute_verified",
    "verify_plan",
}


def _source_files() -> list[Path]:
    files = list(_LOGIX_MCP.rglob("*.py"))
    assert files, f"no .py files found under {_LOGIX_MCP}"
    return files


def _imports_in(path: Path) -> list[tuple[int, str]]:
    """Return [(lineno, module_name)] for each import in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.append((node.lineno, node.module))
    return found


def _calls_in(path: Path) -> list[tuple[int, str]]:
    """Return [(lineno, function_name)] for each call node."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                found.append((node.lineno, func.id))
            elif isinstance(func, ast.Attribute):
                found.append((node.lineno, func.attr))
    return found


# ---------------------------------------------------------------------------
# Import scan
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", _source_files(), ids=lambda p: p.name)
def test_no_trust_internal_imports(path: Path) -> None:
    imports = _imports_in(path)
    for lineno, module in imports:
        for forbidden in _FORBIDDEN_MODULES:
            if module == forbidden or module.startswith(forbidden + "."):
                pytest.fail(
                    f"{path.name}:{lineno} imports forbidden module "
                    f"{module!r} (ADR-0007)"
                )


# ---------------------------------------------------------------------------
# Call scan
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", _source_files(), ids=lambda p: p.name)
def test_no_bypass_function_calls(path: Path) -> None:
    calls = _calls_in(path)
    for lineno, name in calls:
        if name in _FORBIDDEN_FUNCTION_NAMES:
            pytest.fail(
                f"{path.name}:{lineno} calls forbidden function "
                f"{name!r} (ADR-0007)"
            )


# ---------------------------------------------------------------------------
# Positive: allowed imports still work
# ---------------------------------------------------------------------------

def test_package_imports_cleanly():
    """Sanity: importing the package must not have been broken by these
    checks."""
    import logix_mcp
    assert hasattr(logix_mcp, "LogixMCPServer")
    assert hasattr(logix_mcp, "LogixMCPProxy")


# ---------------------------------------------------------------------------
# Manual allowlist for public Logix imports (documents intent)
# ---------------------------------------------------------------------------

_ALLOWED_LOGIX_MODULES = {
    "logix",                    # top-level version etc.
    "logix.tools",              # ToolSpec (allowed by ADR-0007)
    "logix.results",            # Result, Trace, VerificationReport
    "logix.errors",             # Error, code constants
    "logix.context",            # ExecutionContext
    "logix.capabilities",       # Capability dataclass (not build_capability)
    "logix.engine",             # Logix (to call run/verify/execute)
    "logix.schemas",            # Type instances for wrapping upstream tools
    "logix.schemas.types",      # ObjectType etc.
    "logix.schemas.infer",      # annotation-to-type for nested resolution
    "logix.approval",           # for approval-related paths
    "logix.policies",           # Allow/Deny (returned by invariants)
}


def test_imports_from_core_are_in_allowlist() -> None:
    """Every ``logix.*`` import in ``logix_mcp`` must be on the documented
    allowlist. If a new core import is needed, update the ADR and this
    list together."""
    violations: list[tuple[str, int, str]] = []

    for path in _source_files():
        for lineno, module in _imports_in(path):
            if module.startswith("logix.") or module == "logix":
                if module not in _ALLOWED_LOGIX_MODULES:
                    # Check whether a parent is allowed (e.g. logix.schemas.*
                    # imports under logix.schemas).
                    prefix_allowed = any(
                        module.startswith(allowed + ".")
                        for allowed in _ALLOWED_LOGIX_MODULES
                    )
                    if not prefix_allowed:
                        violations.append((path.name, lineno, module))

    assert violations == [], (
        f"logix_mcp imports non-allowlisted core modules: {violations}. "
        f"Update ADR-0007 and _ALLOWED_LOGIX_MODULES together if the "
        f"new import is genuinely needed."
    )