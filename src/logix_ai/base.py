"""
The adapter contract.

This is the entire interface an AI provider adapter implements. Two
methods. Neither has access to the verifier, the executor, or the
capability registry. If an adapter could do anything else, "works with
any AI" would stop being a structural guarantee.

``ToolSpec`` lives in core (``logix.tools``) because
``logix.tools.describe()`` must work without ``logix_ai`` installed. This
module re-exports it for adapter authors, who can import from either
place.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from logix.tools import ToolSpec

__all__ = ["AdapterError", "ProviderAdapter", "ToolSpec"]


@runtime_checkable
class ProviderAdapter(Protocol):
    """
    Translate the catalog out; normalize a proposal in. Nothing else.

    ``parse_proposal`` MUST return a plain dict that will be handed to
    ``logix.verify()`` / ``logix.run()``. It MUST NOT:

      - mark a plan as verified,
      - inject ``"verified": true`` or an equivalent field,
      - resolve ``$ref`` (the verifier does that),
      - read or mutate the capability registry.

    It MAY raise ``AdapterError`` on shapes it cannot translate. The
    caller is expected to translate that to ``INVALID_PLAN`` (or ignore
    the proposal); it never reaches the trust side.
    """

    name: str

    def format_tools(self, specs: list[ToolSpec]) -> Any:
        """Neutral catalog -> provider's tool-definition shape."""
        ...

    def parse_proposal(self, raw: Any) -> dict[str, Any]:
        """
        Provider's tool-call output -> neutral plan dict (untrusted).

        Raises ``AdapterError`` on shapes it cannot translate.
        """
        ...


class AdapterError(Exception):
    """
    Raised by an adapter when it cannot translate.

    Never leaks past the caller. The application translates it to an
    ``INVALID_PLAN`` error (or logs it and drops the proposal). Logix's
    verifier and executor never see this exception.
    """