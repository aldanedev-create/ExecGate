"""
Anthropic Messages API tool-use adapter.

Sample shape: a Message response whose ``content`` list contains a
``tool_use`` block. Anthropic's ``input`` field is already a dict — no
JSON-string parsing.
"""

from __future__ import annotations

import pytest

from logiq_ai.base import AdapterError
from logiq_ai.providers.anthropic import AnthropicAdapter
from tests.adapters.contract import AdapterContractMixin


class TestAnthropicAdapter(AdapterContractMixin):
    def make_adapter(self):
        return AnthropicAdapter()

    def sample_proposal(self):
        return {
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu_abc",
                    "name": "get_order",
                    "input": {"order_id": 502},
                }
            ],
            "stop_reason": "tool_use",
        }


# ---------------------------------------------------------------------------
# Provider-specific behaviors
# ---------------------------------------------------------------------------


def test_name():
    assert AnthropicAdapter().name == "anthropic"


def test_format_tools_shape():
    from tests.adapters.contract import SAMPLE_SPECS

    formatted = AnthropicAdapter().format_tools(SAMPLE_SPECS)
    assert len(formatted) == 2
    for entry in formatted:
        assert set(entry.keys()) == {"name", "description", "input_schema"}


def test_parse_accepts_content_list_directly():
    adapter = AnthropicAdapter()
    plan = adapter.parse_proposal(
        [
            {"type": "tool_use", "name": "get_order", "input": {"order_id": 1}},
        ]
    )
    assert plan == {"call": "get_order", "with": {"order_id": 1}}


def test_parse_accepts_single_tool_use_block():
    adapter = AnthropicAdapter()
    plan = adapter.parse_proposal(
        {
            "type": "tool_use",
            "name": "get_order",
            "input": {"order_id": 2},
        }
    )
    assert plan == {"call": "get_order", "with": {"order_id": 2}}


def test_parse_skips_text_blocks():
    """A response with a text block followed by tool_use must find the
    tool_use, not choke on the text."""
    adapter = AnthropicAdapter()
    plan = adapter.parse_proposal(
        {
            "content": [
                {"type": "text", "text": "Let me look that up."},
                {"type": "tool_use", "name": "get_order", "input": {"order_id": 3}},
            ],
        }
    )
    assert plan == {"call": "get_order", "with": {"order_id": 3}}


def test_parse_handles_missing_input_as_empty_dict():
    adapter = AnthropicAdapter()
    plan = adapter.parse_proposal(
        {
            "type": "tool_use",
            "name": "noop",
            # no "input" key
        }
    )
    assert plan == {"call": "noop", "with": {}}


def test_rejects_no_tool_use():
    adapter = AnthropicAdapter()
    with pytest.raises(AdapterError, match="no tool_use"):
        adapter.parse_proposal({"content": [{"type": "text", "text": "hi"}]})


def test_rejects_invalid_name():
    adapter = AnthropicAdapter()
    with pytest.raises(AdapterError):
        adapter.parse_proposal({"type": "tool_use", "name": "", "input": {}})
