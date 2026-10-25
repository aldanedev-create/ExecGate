"""
Gemini function-calling adapter.

Sample shape: a response whose ``candidates[0].content.parts`` contains
a ``functionCall`` part. Gemini's ``args`` field is already a dict.
"""

from __future__ import annotations

import pytest

from logix_ai.base import AdapterError
from logix_ai.providers.gemini import GeminiAdapter
from tests.adapters.contract import AdapterContractMixin


class TestGeminiAdapter(AdapterContractMixin):
    def make_adapter(self):
        return GeminiAdapter()

    def sample_proposal(self):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "get_order",
                                    "args": {"order_id": 502},
                                }
                            }
                        ],
                    },
                }
            ]
        }


# ---------------------------------------------------------------------------
# Provider-specific behaviors
# ---------------------------------------------------------------------------

def test_name():
    assert GeminiAdapter().name == "gemini"


def test_format_tools_shape():
    from tests.adapters.contract import SAMPLE_SPECS

    formatted = GeminiAdapter().format_tools(SAMPLE_SPECS)
    assert len(formatted) == 2
    for entry in formatted:
        assert set(entry.keys()) == {"name", "description", "parameters"}


def test_parse_accepts_parts_list():
    adapter = GeminiAdapter()
    plan = adapter.parse_proposal([
        {"functionCall": {"name": "get_order", "args": {"order_id": 1}}},
    ])
    assert plan == {"call": "get_order", "with": {"order_id": 1}}


def test_parse_accepts_single_part():
    adapter = GeminiAdapter()
    plan = adapter.parse_proposal({
        "functionCall": {"name": "get_order", "args": {"order_id": 2}},
    })
    assert plan == {"call": "get_order", "with": {"order_id": 2}}


def test_parse_skips_text_parts():
    adapter = GeminiAdapter()
    plan = adapter.parse_proposal({
        "parts": [
            {"text": "Let me look that up."},
            {"functionCall": {"name": "get_order", "args": {"order_id": 3}}},
        ],
    })
    assert plan == {"call": "get_order", "with": {"order_id": 3}}


def test_parse_handles_missing_args_as_empty_dict():
    adapter = GeminiAdapter()
    plan = adapter.parse_proposal({
        "functionCall": {"name": "noop"},
    })
    assert plan == {"call": "noop", "with": {}}


def test_rejects_no_function_call():
    adapter = GeminiAdapter()
    with pytest.raises(AdapterError, match="no functionCall"):
        adapter.parse_proposal({"parts": [{"text": "hi"}]})