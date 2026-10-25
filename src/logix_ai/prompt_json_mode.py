"""
JSON-mode prompt builder for providers without native tool calling.

Returns a system-prompt string that tells the model:

- which capabilities exist (name, description, input schema),
- how to propose a call (a single JSON object),
- that anything not matching this shape will be rejected.

Combine with ``NeutralJSONAdapter`` or ``LocalAdapter`` for parsing the
response. The prompt itself is plain text — the application decides
where to put it (system message, user message, or a JSON-mode wrapper).

Example::

    from logix import Logix
    from logix_ai.prompt_json_mode import build

    logix = Logix()
    @logix.capability
    def get_order(order_id: int) -> dict:
        "Retrieve an order by ID."
        return {"id": order_id}

    specs = logix.tools.describe()
    system = build(specs)
    # pass `system` as the system message to your local model
"""

from __future__ import annotations

import json
from typing import Any

from logix_ai.base import ToolSpec


def build(
    specs: list[ToolSpec],
    *,
    system: str = "",
    strict: bool = True,
) -> str:
    """
    Build a JSON-mode system prompt describing the available capabilities.

    Parameters
    ----------
    specs
        The catalog from ``logix.tools.describe()``.
    system
        Optional prefix text the application wants to prepend (its own
        system prompt). The tool instructions are appended after it.
    strict
        When True (default), the prompt instructs the model to emit a
        single JSON object and nothing else. Set False if the model is
        expected to mix text and JSON.
    """
    capabilities_block = _format_capabilities(specs)
    instructions = _INSTRUCTIONS_STRICT if strict else _INSTRUCTIONS_LENIENT

    parts: list[str] = []
    if system:
        parts.append(system.strip())
    parts.append(capabilities_block)
    parts.append(instructions)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_INSTRUCTIONS_STRICT = """\
To act, emit exactly one JSON object — no prose, no markdown fences, no
commentary before or after. The object MUST have this shape:

  {{"call": "<capability name>", "with": <arguments object>}}

Use only capability names listed above. Arguments must match the input
schema of the chosen capability. If you cannot complete the request
using the available capabilities, emit:

  {{"call": "__no_op__", "with": {{"reason": "<short explanation>"}}}}
"""

_INSTRUCTIONS_LENIENT = """\
To act, include a single JSON object somewhere in your response with
this shape:

  {{"call": "<capability name>", "with": <arguments object>}}

Use only capability names listed above. Arguments must match the input
schema of the chosen capability.
"""


def _format_capabilities(specs: list[ToolSpec]) -> str:
    if not specs:
        return "# Available capabilities\n\n(none registered)"

    lines: list[str] = ["# Available capabilities", ""]
    for spec in specs:
        lines.append(f"## {spec.name}")
        if spec.description:
            lines.append(spec.description)
        if spec.effects:
            lines.append(f"_effects: {spec.effects}_")
        if spec.approval:
            lines.append(f"_approval: {spec.approval}_")
        lines.append("")
        lines.append("Input schema (JSON Schema):")
        lines.append(_json_block(spec.input_schema))
        if spec.output_schema is not None:
            lines.append("Output schema (JSON Schema):")
            lines.append(_json_block(spec.output_schema))
        lines.append("")
    return "\n".join(lines)


def _json_block(obj: Any) -> str:
    return "```json\n" + json.dumps(obj, indent=2, sort_keys=True) + "\n```"