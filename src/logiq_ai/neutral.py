"""
The always-available adapter. Works with any AI that can emit JSON.

This module has no dependencies and no provider knowledge. It is the
reason "works with any AI" is a guarantee rather than a marketing line:
there is always a path from ``ToolSpec`` to a description any client can
read, and from any JSON proposal back to a neutral plan.
"""

from __future__ import annotations

import json
from typing import Any

from logiq_ai.base import AdapterError, ToolSpec


class NeutralJSONAdapter:
    """``tools.format("json")`` — never imports an SDK, never fails to load."""

    name = "json"

    def format_tools(self, specs: list[ToolSpec]) -> list[dict[str, Any]]:
        return [spec.to_neutral_dict() for spec in specs]

    def parse_proposal(self, raw: Any) -> dict[str, Any]:
        # Accept both a JSON string and an already-parsed dict.
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as e:
                raise AdapterError(f"proposal is not valid JSON: {e}") from e

        if not isinstance(raw, dict):
            raise AdapterError(f"proposal must be a JSON object, got {type(raw).__name__}")

        # Do not strip or add anything. If the proposal smuggles "verified",
        # plans.parse will reject it as an unknown top-level field.
        return raw
