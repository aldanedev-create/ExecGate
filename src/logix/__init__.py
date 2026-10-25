"""
Logix — verified execution for AI-generated plans.

The AI proposes. Logix verifies. Trusted code executes.

This module defines the public surface of the core package. Only names
exported here are part of the stable 0.1 contract; everything else in
submodules is internal and may change.

The core is standard-library only. Optional integrations live in
``logix_pydantic`` and ``logix_ai`` and must never be imported from this
package (see ``tests/pydantic/test_core_without_pydantic.py``).
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = [
    "__version__",
    "Logix",
    "Result",
    "VerificationReport",
    "ExecutionContext",
    "Error",
    "VerifiedPlan",
    "Allow",
    "Deny",
    "RequireApproval",
    "ToolSpec",          # NEW

]

# The engine (Phase 1). Imported lazily via __getattr__ so that
# `from logix import Result` does not require the full engine to be
# importable while it is being built. Once engine.py is implemented,
# this can become a plain top-level import.
_LAZY_IMPORTS = {
    "Logix": ("logix.engine", "Logix"),
    "Result": ("logix.results", "Result"),
    "VerificationReport": ("logix.results", "VerificationReport"),
    "ExecutionContext": ("logix.context", "ExecutionContext"),
    "Error": ("logix.errors", "Error"),
    "VerifiedPlan": ("logix.ir", "VerifiedPlan"),
    "Allow": ("logix.policies", "Allow"),
    "Deny": ("logix.policies", "Deny"),
    "RequireApproval": ("logix.policies", "RequireApproval"),
    "ToolSpec": ("logix.tools", "ToolSpec"),   # NEW

}


def __getattr__(name: str):
    """
    Lazy attribute access for public names.

    This keeps ``import logix`` cheap and lets core submodules be written
    in dependency order without circular-import pain. Accessing a name
    that is not exported raises AttributeError, which is the correct
    behaviour for an unknown public API.
    """
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'logix' has no attribute {name!r}")
    module_name, attr_name = target
    from importlib import import_module

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value  # cache after first resolution
    return value


def __dir__() -> list[str]:
    return sorted(__all__)