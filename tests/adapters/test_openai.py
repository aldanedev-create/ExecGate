"""
OpenAI Chat Completions tool-calling adapter.

Sample shape: a full chat completion response with one ``tool_call``.
"""

from __future__ import annotations

import pytest

from execgate_ai.base import AdapterError
from execgate_ai.providers.openai import OpenAIAdapter
from tests.adapters.contract import AdapterContractMixin


class TestOpenAIAdapter(AdapterContractMixin):
    def make_adapter(self):
        return OpenAIAdapter()

    def sample_proposal(self):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {
                                    "name": "get_order",
                                    "arguments": '{"order_id": 502}',
                                },
                            }
                        ],
                    },
                }
            ],
        }


# ---------------------------------------------------------------------------
# Provider-specific behaviors
# ---------------------------------------------------------------------------


def test_name():
    assert OpenAIAdapter().name == "openai"


def test_format_tools_shape():
    from tests.adapters.contract import SAMPLE_SPECS

    formatted = OpenAIAdapter().format_tools(SAMPLE_SPECS)
    assert len(formatted) == 2
    for entry in formatted:
        assert entry["type"] == "function"
        assert "function" in entry
        assert set(entry["function"].keys()) == {"name", "description", "parameters"}


def test_parse_accepts_message_dict():
    adapter = OpenAIAdapter()
    plan = adapter.parse_proposal(
        {
            "tool_calls": [
                {
                    "function": {"name": "get_order", "arguments": '{"order_id": 1}'},
                }
            ],
        }
    )
    assert plan == {"call": "get_order", "with": {"order_id": 1}}


def test_parse_accepts_tool_calls_list():
    adapter = OpenAIAdapter()
    plan = adapter.parse_proposal(
        [
            {"function": {"name": "get_order", "arguments": "{}"}},
        ]
    )
    assert plan == {"call": "get_order", "with": {}}


def test_parse_accepts_single_tool_call():
    adapter = OpenAIAdapter()
    plan = adapter.parse_proposal(
        {
            "function": {"name": "get_order", "arguments": '{"order_id": 3}'},
        }
    )
    assert plan == {"call": "get_order", "with": {"order_id": 3}}


def test_parse_handles_dict_arguments():
    """Newer OpenAI SDKs sometimes return arguments as a dict."""
    adapter = OpenAIAdapter()
    plan = adapter.parse_proposal(
        {
            "function": {"name": "get_order", "arguments": {"order_id": 4}},
        }
    )
    assert plan == {"call": "get_order", "with": {"order_id": 4}}


def test_parse_handles_empty_arguments_string():
    adapter = OpenAIAdapter()
    plan = adapter.parse_proposal(
        {
            "function": {"name": "noop", "arguments": ""},
        }
    )
    assert plan == {"call": "noop", "with": {}}


def test_rejects_no_tool_call():
    adapter = OpenAIAdapter()
    with pytest.raises(AdapterError, match="no tool call"):
        adapter.parse_proposal({"choices": [{"message": {"role": "assistant"}}]})


def test_rejects_invalid_json_arguments():
    adapter = OpenAIAdapter()
    with pytest.raises(AdapterError, match="not valid JSON"):
        adapter.parse_proposal(
            {
                "function": {"name": "get_order", "arguments": "{not json"},
            }
        )


def test_rejects_missing_function_name():
    adapter = OpenAIAdapter()
    with pytest.raises(AdapterError):
        adapter.parse_proposal(
            {
                "function": {"arguments": '{"x": 1}'},
            }
        )
