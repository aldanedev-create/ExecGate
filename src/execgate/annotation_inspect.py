"""
Signature and annotation inspection.

Extracts from a trusted Python function everything the schema engine needs:

- parameter names, kinds, defaults, and (resolved) annotations,
- the return annotation,
- the docstring (for the capability description).

Rejected at inspection time (structural problems — not annotation problems):

- non-callables, classes
- variadic parameters (``*args``, ``**kwargs``) — capabilities have fixed arity
- unbound methods (``self`` / ``cls`` as first parameter)
- async functions — not supported in 0.1.0; wrap in a sync adapter

Rejected later by ``find_unsupported_annotations`` / the schema engine
(annotation problems):

- annotations the native schema engine cannot represent faithfully
  (ADR-0003: reject rather than silently weaken)
- unannotated parameters (a capability must declare every input type)
- string annotations that could not be resolved to a type

This module reads the function; it does not validate values. Those belong
to ``execgate.schemas.validate``.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from execgate.schemas.unsupported import describe_unsupported

__all__ = [
    "ParameterInfo",
    "SignatureInfo",
    "extract_description",
    "find_unsupported_annotations",
    "inspect_capability",
]


# ---------------------------------------------------------------------------
# Data types (public contract; see docs/api-reference.md)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParameterInfo:
    """One parameter of a capability handler, as declared."""

    name: str
    annotation: Any
    """Resolved annotation when possible; ``inspect.Parameter.empty`` when none;
    the raw string when resolution failed (surfaced by
    ``find_unsupported_annotations``)."""

    default: Any
    """Default value, or ``inspect.Parameter.empty`` when required."""

    has_default: bool
    kind: Any
    """``inspect.Parameter.kind`` — positional, keyword, positional-or-keyword."""


@dataclass(frozen=True)
class SignatureInfo:
    """
    Structured view of a handler signature.

    Produced once at registration; the schema engine consumes it. This is
    the only place that touches ``inspect.signature`` for capabilities.
    """

    function_name: str
    parameters: tuple[ParameterInfo, ...]
    return_annotation: Any
    docstring: str | None


# ---------------------------------------------------------------------------
# inspect_capability
# ---------------------------------------------------------------------------


def inspect_capability(fn: Callable[..., Any]) -> SignatureInfo:
    """
    Read a capability function's signature and docstring.

    Structural validation happens here. Annotation validation happens
    later, in ``find_unsupported_annotations`` (or in the schema engine
    directly, which repeats the check).

    Raises
    ------
    TypeError
        If ``fn`` is not a plain Python callable suitable for registration,
        or if its signature has a shape a capability cannot have (variadics,
        unbound method, async).
    """
    if not callable(fn):
        raise TypeError(f"@execgate.capability requires a callable, got {type(fn).__name__}")
    if inspect.isclass(fn):
        raise TypeError(
            f"@execgate.capability requires a function, not a class "
            f"({_display_name(fn)}); wrap the class in a factory function"
        )
    if inspect.iscoroutinefunction(fn):
        raise TypeError(
            f"capability {_display_name(fn)!r} is an async function; "
            f"async handlers are not supported in 0.1.0 — wrap it in a sync "
            f"adapter (e.g. ``asyncio.run(...)``)"
        )

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as e:
        raise TypeError(f"cannot inspect signature of {_display_name(fn)}: {e}") from e

    params = list(sig.parameters.values())

    # Variadic parameters are structurally incompatible with a fixed-arity
    # capability schema. Reject here so the error names the parameter.
    for p in params:
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            raise TypeError(
                f"capability {_display_name(fn)!r} uses *{p.name}; "
                f"variadic parameters are not supported (capabilities have "
                f"fixed arity)"
            )
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            raise TypeError(
                f"capability {_display_name(fn)!r} uses **{p.name}; "
                f"variadic parameters are not supported (capabilities have "
                f"fixed arity)"
            )

    # Unbound methods on a class: ``self`` / ``cls`` would be exposed as a
    # required parameter. Reject with a clear message.
    if params and params[0].name in ("self", "cls"):
        raise TypeError(
            f"capability {_display_name(fn)!r} has {params[0].name!r} as its "
            f"first parameter; register a bound method or a plain function "
            f"instead"
        )

    # Resolve string annotations (e.g. ``from __future__ import annotations``
    # or explicit forward references). If resolution fails, keep the raw
    # annotations; ``find_unsupported_annotations`` will report them clearly.
    try:
        resolved = typing.get_type_hints(fn, include_extras=True)
    except Exception:
        resolved = {}

    parameters = tuple(
        ParameterInfo(
            name=p.name,
            annotation=resolved.get(p.name, p.annotation),
            default=p.default,
            has_default=(p.default is not inspect.Parameter.empty),
            kind=p.kind,
        )
        for p in params
    )

    return_annotation = resolved.get("return", sig.return_annotation)

    return SignatureInfo(
        function_name=getattr(fn, "__name__", "<unnamed>"),
        parameters=parameters,
        return_annotation=return_annotation,
        docstring=inspect.getdoc(fn),
    )


# ---------------------------------------------------------------------------
# extract_description
# ---------------------------------------------------------------------------


def extract_description(
    fn: Callable[..., Any],
    *,
    override: str | None = None,
) -> str:
    """
    Return the capability description.

    Precedence: explicit ``override`` > normalized docstring > empty string.
    Never includes the function's source. Returns an empty string (not
    ``None``) so callers have a stable type to embed in ``ToolSpec``.
    """
    if override is not None:
        if not isinstance(override, str):
            raise TypeError(f"description override must be a string, got {type(override).__name__}")
        return override
    return inspect.getdoc(fn) or ""


# ---------------------------------------------------------------------------
# find_unsupported_annotations
# ---------------------------------------------------------------------------


def find_unsupported_annotations(info: SignatureInfo) -> list[str]:
    """
    Return human-readable descriptions of annotations the schema engine
    cannot represent faithfully.

    Empty list means every annotation is supported and registration may
    proceed. Non-empty means registration must fail — never silently
    weaken validation (ADR-0003).

    Each returned string names the offending parameter (or ``return``) so
    a single registration attempt reports every problem at once.
    """
    problems: list[str] = []

    for param in info.parameters:
        # Unresolved string annotation: report specifically rather than
        # letting describe_unsupported call it "unsupported".
        if isinstance(param.annotation, str):
            problems.append(
                f"parameter {param.name!r}: annotation {param.annotation!r} "
                f"could not be resolved to a type (ensure the type is "
                f"importable at registration time)"
            )
            continue

        for problem in describe_unsupported(param.annotation):
            problems.append(f"parameter {param.name!r}: {problem}")

    # An unannotated return is allowed — output validation is skipped for
    # that capability. Only report unsupported *declared* returns.
    if info.return_annotation is not inspect.Signature.empty:
        if isinstance(info.return_annotation, str):
            problems.append(
                f"return: annotation {info.return_annotation!r} could not be "
                f"resolved to a type (ensure the type is importable at "
                f"registration time)"
            )
        else:
            for problem in describe_unsupported(info.return_annotation):
                problems.append(f"return: {problem}")

    return problems


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _display_name(fn: Any) -> str:
    """Best-effort human name for error messages."""
    name = getattr(fn, "__name__", None)
    if isinstance(name, str) and name:
        return name
    return repr(fn)
