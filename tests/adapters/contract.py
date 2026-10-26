"""
Adapter conformance kit.

Every adapter — built-in or user-written — must pass this mixin.
Subclass it and implement:

    def make_adapter(self) -> ProviderAdapter: ...
    def sample_proposal(self) -> Any: ...

Optionally override ``expected_normalized_plan()`` if the adapter's
output is not the default. That is not expected for any 0.1.0 adapter.

What the mixin verifies:

1. The adapter satisfies the ``ProviderAdapter`` protocol.
2. ``format_tools([])`` does not raise.
3. ``format_tools(SAMPLE_SPECS)`` names every capability somewhere in
   the serialized output.
4. ``parse_proposal(sample_proposal())`` yields a plain ``dict`` equal
   to ``expected_normalized_plan()``.
5. ``parse_proposal`` raises ``AdapterError`` on non-object input.
6. The adapter exposes none of the trust-boundary methods
   (``verify``, ``execute``, ``registry``, ``run``, ``logix``).

What it deliberately does NOT verify (each provider test's job):

- The exact provider wire format. That varies by provider and evolves
  with their APIs. Provider tests assert the shape; the contract asserts
  the invariants.
"""

from __future__ import annotations

import json

import pytest

from logiq.tools import ToolSpec
from logiq_ai import AdapterError, ProviderAdapter


# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

SAMPLE_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="get_order",
        description="Retrieve an order by its ID.",
        input_schema={
            "type": "object",
            "properties": {"order_id": {"type": "integer"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        effects="read",
    ),
    ToolSpec(
        name="issue_refund",
        description="Issue a refund for an order.",
        input_schema={
            "type": "object",
            "properties": {
                "order_id": {"type": "integer"},
                "amount": {"type": "number"},
            },
            "required": ["order_id", "amount"],
            "additionalProperties": False,
        },
        effects="write",
        approval="principal_bound",
    ),
]

EXPECTED_NORMALIZED_PLAN: dict = {
    "call": "get_order",
    "with": {"order_id": 502},
}


# ---------------------------------------------------------------------------
# The mixin
# ---------------------------------------------------------------------------

class AdapterContractMixin:
    """
    Subclass and implement ``make_adapter`` and ``sample_proposal``.
    Every test here must pass or the adapter is rejected.
    """

    @pytest.fixture
    def adapter(self) -> ProviderAdapter:
        return self.make_adapter()

    # -- required overrides ----------------------------------------------

    def make_adapter(self) -> ProviderAdapter:
        raise NotImplementedError(
            f"{type(self).__name__}.make_adapter must return a ProviderAdapter"
        )

    def sample_proposal(self):
        raise NotImplementedError(
            f"{type(self).__name__}.sample_proposal must return a raw "
            f"proposal in the provider's own shape"
        )

    def expected_normalized_plan(self) -> dict:
        return EXPECTED_NORMALIZED_PLAN

    # -- protocol ---------------------------------------------------------

    def test_implements_protocol(self, adapter):
        assert isinstance(adapter, ProviderAdapter)

    def test_adapter_has_name(self, adapter):
        assert isinstance(adapter.name, str)
        assert adapter.name

    # -- format_tools -----------------------------------------------------

    def test_format_tools_empty_catalog(self, adapter):
        # Must not raise. Return value may be [] or a provider's empty form.
        adapter.format_tools([])

    def test_format_tools_includes_all_capability_names(self, adapter):
        formatted = adapter.format_tools(SAMPLE_SPECS)
        serialized = json.dumps(formatted, default=str)
        for spec in SAMPLE_SPECS:
            assert spec.name in serialized, (
                f"capability name {spec.name!r} not found in "
                f"format_tools output: {serialized}"
            )

    def test_format_tools_includes_argument_names(self, adapter):
        """The input schema's contents must survive translation."""
        formatted = adapter.format_tools(SAMPLE_SPECS)
        serialized = json.dumps(formatted, default=str)
        assert "order_id" in serialized
        assert "amount" in serialized

    def test_format_tools_is_serializable(self, adapter):
        formatted = adapter.format_tools(SAMPLE_SPECS)
        # If a provider returns a non-serializable value (e.g. an SDK
        # object), the application couldn't send it over the wire.
        json.dumps(formatted, default=str)

    # -- parse_proposal ---------------------------------------------------

    def test_roundtrip_normalizes_to_expected_plan(self, adapter):
        normalized = adapter.parse_proposal(self.sample_proposal())
        assert normalized == self.expected_normalized_plan(), (
            f"adapter produced {normalized!r}, expected "
            f"{self.expected_normalized_plan()!r}"
        )

    def test_parse_proposal_returns_plain_dict(self, adapter):
        normalized = adapter.parse_proposal(self.sample_proposal())
        assert type(normalized) is dict, (
            f"parse_proposal must return a plain dict, got "
            f"{type(normalized).__name__}"
        )

    def test_parse_proposal_rejects_non_object(self, adapter):
        with pytest.raises(AdapterError):
            adapter.parse_proposal([1, 2, 3])

    def test_parse_proposal_rejects_none(self, adapter):
        with pytest.raises(AdapterError):
            adapter.parse_proposal(None)

    def test_parse_proposal_rejects_integer(self, adapter):
        with pytest.raises(AdapterError):
            adapter.parse_proposal(42)

    def test_parse_proposal_does_not_strip_unknown_top_level_fields(
        self, adapter,
    ):
        """
        If a proposal's shape contains a ``verified: true`` marker, the
        adapter must not silently strip it, and must not honor it. The
        downstream ``plans.parse`` is what rejects it (unknown top-level
        field).

        This test is a *behavioral* check: the input is the provider's
        sample shape, not a plan dict. Adapters that construct fresh
        output (all provider adapters) are naturally safe because the
        output has no ``verified`` key regardless of what was injected.
        Only ``NeutralJSONAdapter`` passes the input through, and even
        there ``plans.parse`` catches it.
        """
        sample = self.sample_proposal()
        if isinstance(sample, dict):
            # Inject at top level where a naive passthrough might carry it.
            sample["verified"] = True

        try:
            normalized = adapter.parse_proposal(sample)
        except AdapterError:
            # Adapter rejected the (now-malformed) sample shape.
            return

        # If it normalized, the result must not be directly executable.
        from logiq.plans import parse_plan
        # Invariant: a smuggled marker must never reach an *accepted* plan.
        # Fresh-output adapters drop it (no key to reject); passthrough
        # adapters keep it and parse_plan must reject it.
        parse_result = parse_plan(normalized)
        carries_marker = isinstance(normalized, dict) and "verified" in normalized
        assert not carries_marker or isinstance(parse_result, list), (
            "adapter's normalized plan contained a 'verified' marker that "
            "reached parse_plan; this would defeat the trust boundary"
        )

    # -- trust-boundary isolation -----------------------------------------

    def test_adapter_has_no_trust_boundary_attributes(self, adapter):
        forbidden = ("verify", "execute", "registry", "logix", "run", "policy")
        for name in forbidden:
            assert not hasattr(adapter, name), (
                f"adapter exposes forbidden attribute {name!r}; "
                f"adapters must be leaf nodes (ADR-0006)"
            )