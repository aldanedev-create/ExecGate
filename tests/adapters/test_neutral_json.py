"""
The always-available neutral adapter.

``NeutralJSONAdapter`` passes plans through untouched (except for the
JSON-string convenience) and produces the neutral JSON Schema catalog.
It also serves as the fallback for every unrecognized provider name —
the foundation of "works with any AI that emits JSON".
"""

from __future__ import annotations

import pytest

from logiq_ai import (
    NeutralJSONAdapter,
    get_adapter,
)
from logiq_ai.base import AdapterError
from tests.adapters.contract import AdapterContractMixin


class TestNeutralJSONAdapter(AdapterContractMixin):
    def make_adapter(self):
        return NeutralJSONAdapter()

    def sample_proposal(self):
        return {"call": "get_order", "with": {"order_id": 502}}


# ---------------------------------------------------------------------------
# Provider-specific behaviors
# ---------------------------------------------------------------------------


def test_name():
    assert NeutralJSONAdapter().name == "json"


def test_format_tools_returns_neutral_dicts():
    """The neutral shape is exactly ``ToolSpec.to_neutral_dict()``."""
    from tests.adapters.contract import SAMPLE_SPECS

    adapter = NeutralJSONAdapter()
    formatted = adapter.format_tools(SAMPLE_SPECS)

    assert formatted == [spec.to_neutral_dict() for spec in SAMPLE_SPECS]


def test_parse_proposal_accepts_json_string():
    adapter = NeutralJSONAdapter()
    plan = adapter.parse_proposal('{"call": "get_order", "with": {"order_id": 1}}')
    assert plan == {"call": "get_order", "with": {"order_id": 1}}


def test_parse_proposal_rejects_invalid_json_string():
    adapter = NeutralJSONAdapter()
    with pytest.raises(AdapterError, match="not valid JSON"):
        adapter.parse_proposal("{not json")


def test_parse_proposal_passes_through_unchanged():
    """Neutral does not add, remove, or rename any field."""
    original = {"call": "x", "with": {"a": 1}}
    assert NeutralJSONAdapter().parse_proposal(original) == original


# ---------------------------------------------------------------------------
# Registry fallback
# ---------------------------------------------------------------------------


def test_get_adapter_json_returns_neutral():
    adapter = get_adapter("json")
    assert isinstance(adapter, NeutralJSONAdapter)


def test_get_adapter_neutral_returns_neutral():
    adapter = get_adapter("neutral")
    assert isinstance(adapter, NeutralJSONAdapter)


def test_get_adapter_unknown_returns_neutral():
    """The core promise: any provider name yields a working adapter."""
    adapter = get_adapter("provider-that-does-not-exist")
    assert isinstance(adapter, NeutralJSONAdapter)


def test_get_adapter_case_insensitive():
    assert isinstance(get_adapter("JSON"), NeutralJSONAdapter)
    assert isinstance(get_adapter("  JSON  "), NeutralJSONAdapter)


def test_get_adapter_known_providers():
    from logiq_ai.providers.anthropic import AnthropicAdapter
    from logiq_ai.providers.gemini import GeminiAdapter
    from logiq_ai.providers.local import LocalAdapter
    from logiq_ai.providers.openai import OpenAIAdapter

    assert isinstance(get_adapter("openai"), OpenAIAdapter)
    assert isinstance(get_adapter("anthropic"), AnthropicAdapter)
    assert isinstance(get_adapter("gemini"), GeminiAdapter)
    assert isinstance(get_adapter("local"), LocalAdapter)
