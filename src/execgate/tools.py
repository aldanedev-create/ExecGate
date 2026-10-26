"""
AI discovery interface.

``execgate.tools`` is the only view of the engine an AI is allowed to see.
It exposes capability descriptions as JSON Schema, never handler source,
database credentials, or internal application objects.

Two entry points:

- ``describe()`` — provider-neutral ``ToolSpec`` list.
- ``format(provider)`` — provider-shaped catalog. ``"json"`` is the
  always-available path and the basis of "works with any AI that emits
  JSON". Unknown providers fall back to ``"json"``; they never raise.

``ToolSpec`` lives here (not in ``execgate_ai``) because ``describe()`` must
work when no AI adapter is installed. ``execgate_ai`` imports it from here.

See ``docs/api-reference.md §10`` and ``docs/ai-integration.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from execgate.capabilities import Capability, Registry


__all__ = ["ToolCatalog", "ToolSpec"]


# ---------------------------------------------------------------------------
# ToolSpec — the provider-neutral capability description
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """
    Neutral description of one capability, suitable for feeding to any AI
    that can read JSON Schema.

    ``input_schema`` and ``output_schema`` are JSON Schema dicts (the
    same schemas the verifier uses; the catalog and the validator cannot
    disagree). ``effects`` is an advisory ``"read"`` / ``"write"`` / None.
    ``approval`` is ``"required"`` / ``"principal_bound"`` / None.

    Equality is structural and based on all fields, which means an
    adapter's ``format_tools`` output can be round-tripped through
    ``parse_proposal`` without the spec changing — the conformance kit
    in ``tests/adapters/contract.py`` relies on this.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    effects: str | None = None
    approval: str | None = None
    schema_version: str = "1"

    def to_neutral_dict(self) -> dict[str, Any]:
        """The universal JSON form. Every adapter must preserve these fields."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "effects": self.effects,
            "approval": self.approval,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# ToolCatalog
# ---------------------------------------------------------------------------


class ToolCatalog:
    """Read-only view over the registry for AI discovery."""

    __slots__ = ("_registry",)

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def describe(self) -> list[ToolSpec]:
        """
        Provider-neutral ``ToolSpec`` list, one per registered capability.

        Order matches registration order (the same order the registry
        iterates). Contains no handler source, no secrets, no internal
        application objects — only what an AI needs to propose a valid
        action.
        """
        return [self._spec_for(cap) for cap in self._registry]

    def format(self, provider: str = "json") -> Any:
        """
        Provider-shaped catalog.

        - ``"json"`` (or any unknown provider): returns the neutral list
          of dicts from ``describe()``. Requires no optional package.
        - A named provider (``"openai"``, ``"anthropic"``, ``"gemini"``,
          ``"local"``): delegates to that adapter if ``execgate_ai`` is
          installed and the adapter is registered. Falls back to
          ``"json"`` in every other case — this method never raises on an
          unknown provider name.

        This fallback behaviour is the operational meaning of "works with
        any AI that emits JSON": there is always a usable catalog, whether
        or not the provider has a dedicated adapter.
        """
        specs = self.describe()

        if provider == "json":
            return [s.to_neutral_dict() for s in specs]

        # Try the optional adapter package. Any failure falls back.
        try:
            from execgate_ai import get_adapter
        except ImportError:
            return [s.to_neutral_dict() for s in specs]

        try:
            adapter = get_adapter(provider)
        except Exception:
            return [s.to_neutral_dict() for s in specs]

        return adapter.format_tools(specs)

    def for_capability(self, name: str) -> ToolSpec:
        """Single-capability ``ToolSpec``. Raises ``KeyError`` if absent."""
        cap = self._registry.get(name)
        return self._spec_for(cap)

    def names(self) -> list[str]:
        """Registered capability names, in registration order."""
        return self._registry.names()

    # -- internals --------------------------------------------------------

    @staticmethod
    def _spec_for(cap: Capability) -> ToolSpec:
        return ToolSpec(
            name=cap.name,
            description=cap.description,
            input_schema=cap.input_schema.to_json_schema(),
            output_schema=(
                cap.output_schema.to_json_schema() if cap.output_schema is not None else None
            ),
            effects=cap.effects,
            approval="required" if cap.requires_approval else None,
            schema_version="1",
        )
