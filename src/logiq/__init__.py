"""
Logix — verified execution for AI-generated plans.

The AI proposes. Logix verifies. Trusted code executes.

This module defines the public surface of the core package. Only names
exported here are part of the stable 0.1 contract; everything else in
submodules is internal and may change.

The core is standard-library only. Optional integrations live in
``logiq_pydantic`` and ``logiq_ai`` and must never be imported from this
package (see ``tests/pydantic/test_core_without_pydantic.py``).
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = [
    "Allow",
    "Deny",
    "Error",
    "ExecutionContext",
    "Logix",
    "RequireApproval",
    "Result",
    "ToolSpec",  # NEW
    "VerificationReport",
    "VerifiedPlan",
    "__version__",
]

# The engine (Phase 1). Imported lazily via __getattr__ so that
# `from logiq import Result` does not require the full engine to be
# importable while it is being built. Once engine.py is implemented,
# this can become a plain top-level import.
_LAZY_IMPORTS = {
    "Logix": ("logiq.engine", "Logix"),
    "Result": ("logiq.results", "Result"),
    "VerificationReport": ("logiq.results", "VerificationReport"),
    "ExecutionContext": ("logiq.context", "ExecutionContext"),
    "Error": ("logiq.errors", "Error"),
    "VerifiedPlan": ("logiq.ir", "VerifiedPlan"),
    "Allow": ("logiq.policies", "Allow"),
    "Deny": ("logiq.policies", "Deny"),
    "RequireApproval": ("logiq.policies", "RequireApproval"),
    "ToolSpec": ("logiq.tools", "ToolSpec"),  # NEW
}


def __getattr__(name: str) -> object:
    """
    Lazy attribute access for public names.

    This keeps ``import logiq`` cheap and lets core submodules be written
    in dependency order without circular-import pain. Accessing a name
    that is not exported raises AttributeError, which is the correct
    behaviour for an unknown public API.
    """
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'logiq' has no attribute {name!r}")
    module_name, attr_name = target
    from importlib import import_module

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value  # cache after first resolution
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
