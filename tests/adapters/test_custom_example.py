"""
The reference custom adapter.

Exercises the ~30-line ``custom_example.ExampleAdapter``. This file is the
canonical template: copy it when writing a new provider adapter — only
``make_adapter`` and ``sample_proposal`` change.
"""

from __future__ import annotations

import pytest

from execgate_ai.base import AdapterError
from execgate_ai.custom_example import ExampleAdapter
from tests.adapters.contract import AdapterContractMixin


class TestCustomExampleAdapter(AdapterContractMixin):
    def make_adapter(self):
        return ExampleAdapter()

    def sample_proposal(self):
        return {
            "chosen_tool": {
                "tool_name": "get_order",
                "tool_args": {"order_id": 502},
            }
        }


# ---------------------------------------------------------------------------
# Provider-specific behaviors
# ---------------------------------------------------------------------------


def test_name():
    assert ExampleAdapter().name == "example"


def test_format_tools_shape():
    from tests.adapters.contract import SAMPLE_SPECS

    formatted = ExampleAdapter().format_tools(SAMPLE_SPECS)
    assert len(formatted) == 2
    for entry in formatted:
        assert set(entry.keys()) == {
            "tool_name",
            "tool_description",
            "args_schema",
        }


def test_parse_rejects_non_dict():
    adapter = ExampleAdapter()
    with pytest.raises(AdapterError):
        adapter.parse_proposal("not-a-dict")


def test_parse_rejects_missing_chosen_tool():
    adapter = ExampleAdapter()
    with pytest.raises(AdapterError, match="chosen_tool"):
        adapter.parse_proposal({"other": "x"})


def test_parse_rejects_invalid_tool_name():
    adapter = ExampleAdapter()
    with pytest.raises(AdapterError):
        adapter.parse_proposal(
            {
                "chosen_tool": {"tool_name": "", "tool_args": {}},
            }
        )


def test_parse_rejects_non_dict_tool_args():
    adapter = ExampleAdapter()
    with pytest.raises(AdapterError):
        adapter.parse_proposal(
            {
                "chosen_tool": {"tool_name": "get_order", "tool_args": "oops"},
            }
        )


def test_parse_defaults_missing_tool_args_to_empty_dict():
    adapter = ExampleAdapter()
    plan = adapter.parse_proposal({"chosen_tool": {"tool_name": "get_order"}})
    assert plan == {"call": "get_order", "with": {}}


# ---------------------------------------------------------------------------
# Documentation fixture: unregistered
# ---------------------------------------------------------------------------


def test_example_adapter_is_not_registered():
    """Per its docstring, ``ExampleAdapter`` is a reference template only.
    It must not be resolvable via ``get_adapter``."""
    from execgate_ai import get_adapter
    from execgate_ai.neutral import NeutralJSONAdapter

    # "example" is not a registered provider → neutral fallback.
    assert isinstance(get_adapter("example"), NeutralJSONAdapter)
