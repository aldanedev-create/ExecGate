"""
Provider name -> adapter lookup.

Unknown provider names fall back to the neutral ``"json"`` adapter so
that ``logiq.tools.format("some-new-provider")`` never raises — it
returns a usable catalog. Provider modules are lazy-imported; the
package does not pull in any provider's module (or any SDK) until a
caller asks for a specific adapter.
"""

from __future__ import annotations

import importlib

from logiq_ai.base import ProviderAdapter
from logiq_ai.neutral import NeutralJSONAdapter

__all__ = ["get_adapter"]


# Map from provider name to (module path, class name). Every entry is
# lazy-resolved at call time.
_PROVIDERS: dict[str, tuple[str, str]] = {
    "openai": ("logiq_ai.providers.openai", "OpenAIAdapter"),
    "anthropic": ("logiq_ai.providers.anthropic", "AnthropicAdapter"),
    "gemini": ("logiq_ai.providers.gemini", "GeminiAdapter"),
    "local": ("logiq_ai.providers.local", "LocalAdapter"),
}


def get_adapter(name: str) -> ProviderAdapter:
    """
    Return a ``ProviderAdapter`` for the given provider name.

    Falls back to ``NeutralJSONAdapter`` for unknown names, so callers do
    not have to distinguish "provider known" from "provider unknown" —
    every name returns a usable adapter.

    Lazy-imports the provider module only when a specific provider is
    requested. A failure to import (e.g. the provider module has a bug)
    also falls back to neutral rather than raising — the contract is
    "always return a working adapter".
    """
    normalized = name.strip().lower()

    if normalized in ("json", "neutral"):
        return NeutralJSONAdapter()

    entry = _PROVIDERS.get(normalized)
    if entry is None:
        return NeutralJSONAdapter()

    module_name, class_name = entry
    try:
        module = importlib.import_module(module_name)
        adapter_cls = getattr(module, class_name)
        return adapter_cls()  # type: ignore[no-any-return]
    except (ImportError, AttributeError):
        # A broken provider module must not break the application. Fall
        # back to neutral — the caller gets a valid, if unoptimized,
        # adapter.
        return NeutralJSONAdapter()
