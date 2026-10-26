"""
Provider translation adapters for AI tool-calling.

This package has **zero runtime dependencies**. It shapes JSON Schema for
provider-specific tool definitions and parses provider-specific response
shapes into neutral plan dicts. It does not import any provider SDK — the
application has the SDK and makes the model call; the adapter translates
at the edges.

The package is a **leaf node** (ADR-0006): it imports ``ToolSpec`` from
core, and nothing from ``logiq.verifier``, ``logiq.executor``,
``logiq.ir``, or ``logiq.capabilities``. Any adapter must remain leaf-shaped.

Public surface::

    from logiq_ai import ProviderAdapter, AdapterError, ToolSpec, get_adapter

    adapter = get_adapter("openai")               # or "anthropic", ...
    tools = adapter.format_tools(specs)           # shape for the API call
    plan = adapter.parse_proposal(response_dict)  # extract plan from response

Unknown provider names fall back to the neutral ``"json"`` adapter. This
is what makes ``logiq.tools.format(provider)`` never raise on an unknown
name, and what backs the "works with any AI that emits JSON" guarantee.
"""

from __future__ import annotations

from logiq_ai.base import AdapterError, ProviderAdapter, ToolSpec
from logiq_ai.neutral import NeutralJSONAdapter
from logiq_ai.registry import get_adapter

__all__ = [
    "AdapterError",
    "NeutralJSONAdapter",
    "ProviderAdapter",
    "ToolSpec",
    "get_adapter",
]