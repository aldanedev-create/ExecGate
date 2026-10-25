"""
Plan versioning and builder API.

``plan_version()`` reports the version this build of Logix understands.
``plan(...)`` is the developer-facing builder helper (reserved in 0.1.0).

Plans produced by hand, by an AI, or by ``logix.plan(...)`` all go through
``plans.parse_plan``. There is no privileged form.
"""

from __future__ import annotations

from typing import Any


def plan_version() -> str:
    """Return the latest plan format version supported by this build."""
    return "1"


def plan(*steps: Any) -> dict[str, Any]:
    """
    Build a plan in the canonical multi-step form.

    Developer helper; not required for AI-generated plans. Accepts step
    descriptors and assembles the ``{"version": "1", "steps": [...]}``
    envelope. The result is untrusted data — it still goes through
    ``parse_plan`` before verification.

    See ``docs/api-reference.md §13``. (experimental, reserved)
    """
    raise NotImplementedError("plans.format.plan — reserved for 0.1.0")