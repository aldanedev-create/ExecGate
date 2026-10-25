"""
Local model adapter (Ollama / llama.cpp / vLLM in JSON mode).

Sample shape: an Ollama-style response with a JSON string in
``response``.
"""

from __future__ import annotations

import pytest

from logix_ai.base import AdapterError
from logix_ai.providers.local import LocalAdapter
from tests.adapters.contract import AdapterContractMixin


class TestLocalAdapter(AdapterContractMixin):
    def make_adapter(self):
        return LocalAdapter()

    def sample_proposal(self):
        return {
            "response": '{"call": "get_order", "with": {"order_id": 502}}',
        }


# ---------------------------------------------------------------------------
# Provider-specific behaviors
# ---------------------------------------------------------------------------

def test_name():
    assert LocalAdapter().name == "local"


def test_format_tools_returns_neutral():
    """Local models consume the neutral form; no provider-specific shape."""
    from logix_ai.neutral import NeutralJSONAdapter
    from tests.adapters.contract import SAMPLE_SPECS

    local = LocalAdapter().format_tools(SAMPLE_SPECS)
    neutral = NeutralJSONAdapter().format_tools(SAMPLE_SPECS)
    assert local == neutral


def test_parse_accepts_raw_string():
    adapter = LocalAdapter()
    plan = adapter.parse_proposal('{"call": "get_order", "with": {"order_id": 1}}')
    assert plan == {"call": "get_order", "with": {"order_id": 1}}


def test_parse_accepts_ollama_response_field():
    adapter = LocalAdapter()
    plan = adapter.parse_proposal({"response": '{"call": "x", "with": {}}'})
    assert plan == {"call": "x", "with": {}}


def test_parse_accepts_llamacpp_content_field():
    adapter = LocalAdapter()
    plan = adapter.parse_proposal({"content": '{"call": "x", "with": {}}'})
    assert plan == {"call": "x", "with": {}}


def test_parse_accepts_openai_compatible_choices():
    adapter = LocalAdapter()
    plan = adapter.parse_proposal({
        "choices": [{"message": {"content": '{"call": "x", "with": {}}'}}],
    })
    assert plan == {"call": "x", "with": {}}


def test_parse_accepts_vllm_text_field():
    adapter = LocalAdapter()
    plan = adapter.parse_proposal({"text": '{"call": "x", "with": {}}'})
    assert plan == {"call": "x", "with": {}}


def test_rejects_invalid_json():
    adapter = LocalAdapter()
    with pytest.raises(AdapterError, match="not valid JSON"):
        adapter.parse_proposal({"response": "{not json"})


def test_rejects_json_array():
    adapter = LocalAdapter()
    with pytest.raises(AdapterError, match="must be a JSON object"):
        adapter.parse_proposal({"response": '[1, 2, 3]'})


def test_rejects_no_text_field():
    adapter = LocalAdapter()
    with pytest.raises(AdapterError, match="no text"):
        adapter.parse_proposal({"unrelated": "content"})