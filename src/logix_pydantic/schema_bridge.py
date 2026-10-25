"""
Bridge between Pydantic models and the Logix schema system.

``PydanticType`` is a ``logix.schemas.Type`` implementation that delegates
validation to Pydantic, exports the model's JSON Schema for the AI catalog,
and walks its fields for ``$ref`` type-checking in the verifier.

The runtime validator, the catalog, and the reference walker all use the
same model, so they cannot disagree.
"""

from __future__ import annotations

import typing
from typing import Any

import pydantic
from pydantic import BaseModel, TypeAdapter

from logix.schemas.types import SchemaError, Type

__all__ = ["PydanticType", "model_to_json_schema", "model_to_logix_type"]


def model_to_logix_type(model_cls: type[BaseModel]) -> "PydanticType":
    """Wrap a Pydantic model class as a Logix ``Type``."""
    return PydanticType(model_cls)


def model_to_json_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """
    Return the model's JSON Schema.

    Uses Pydantic's own export, so ``Field`` constraints, nested models,
    aliases, ``model_config`` strictness, and ``extra="forbid"`` all flow
    through.
    """
    return model_cls.model_json_schema()


class PydanticType:
    """
    A Logix ``Type`` backed by a Pydantic model.

    - ``validate(value, path)`` runs Pydantic validation and translates
      failures to ``logix.schemas.SchemaError``.
    - ``to_json_schema()`` returns Pydantic's JSON Schema.
    - ``walk(segment)`` resolves a field name to its Logix ``Type`` for
      verify-time reference checking. Handles nested models and
      ``Optional[Model]`` fields.
    - ``prepare_input(value, mode)`` converts the validated value for the
      handler according to ``HandlerMode``.
    - ``prepare_output(value)`` normalizes a handler's return to a
      JSON-safe dict so ``Result.value`` and ``$ref`` traversal work.
    """

    def __init__(self, model_cls: type[BaseModel]) -> None:
        if not (isinstance(model_cls, type) and issubclass(model_cls, BaseModel)):
            raise TypeError(
                f"PydanticType requires a BaseModel subclass, got {model_cls!r}"
            )
        self._model_cls = model_cls
        self._adapter = TypeAdapter(model_cls)

    # -- Type protocol -----------------------------------------------------

    def validate(self, value: Any, path: str = "$") -> list[SchemaError]:
        try:
            self._adapter.validate_python(value)
        except pydantic.ValidationError as exc:
            return _translate_errors(exc, path)
        return []

    def to_json_schema(self) -> dict[str, Any]:
        return self._model_cls.model_json_schema()

    def walk(self, segment: str) -> "Type | None":
        """
        Resolve a field name to its Logix ``Type`` for verify-time
        reference type-checking.

        Returns None if the field does not exist or its annotation cannot
        be mapped (e.g. an exotic Pydantic-typed annotation we do not
        support). A None here means a plan that references this field
        through a ``$ref`` will be rejected at verify time, which is the
        safe default.
        """
        fields = self._model_cls.model_fields
        if segment not in fields:
            return None
        annotation = fields[segment].annotation

        # Unwrap Optional[X] to X when there is exactly one non-None member.
        origin = typing.get_origin(annotation)
        if origin is typing.Union:
            args = typing.get_args(annotation)
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                annotation = non_none[0]

        # Nested Pydantic model: wrap it so reference walking can continue.
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return PydanticType(annotation)

        # Fall back to native inference for primitives and containers.
        from logix.schemas.infer import _annotation_to_type
        try:
            return _annotation_to_type(annotation)
        except Exception:
            return None

    # -- handler preparation ----------------------------------------------

    def prepare_input(self, value: Any, mode: str) -> Any:
        """
        Convert a validated value into what the handler receives.

        - ``"model"``: a Pydantic model instance.
        - ``"values"``: the model's ``model_dump(mode="json")``.
        """
        instance = self._adapter.validate_python(value)
        if mode == "values":
            return instance.model_dump(mode="json")
        return instance

    def prepare_output(self, value: Any) -> Any:
        """
        Normalize a handler's return value for ``Result.value`` and for
        ``$ref`` traversal in subsequent steps.

        Accepts a model instance, a plain dict, or anything Pydantic can
        validate. Returns a JSON-safe dict.
        """
        instance = self._adapter.validate_python(value)
        return instance.model_dump(mode="json")

    # -- introspection -----------------------------------------------------

    @property
    def model_cls(self) -> type[BaseModel]:
        return self._model_cls

    def __repr__(self) -> str:
        return f"PydanticType({self._model_cls.__name__})"


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------

def _translate_errors(exc: pydantic.ValidationError, base_path: str) -> list[SchemaError]:
    """
    Convert ``ValidationError.errors()`` to ``SchemaError``.

    Drops ``input`` (raw values can contain sensitive data). Keeps
    ``type`` and ``msg`` in the message for developer ergonomics.
    """
    out: list[SchemaError] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        path = base_path
        for part in loc:
            if isinstance(part, int):
                path = f"{path}[{part}]"
            else:
                path = f"{path}.{part}" if path else str(part)
        msg = err.get("msg", "validation failed")
        err_type = err.get("type", "")
        display = f"{msg} ({err_type})" if err_type else msg
        out.append(SchemaError(path, display))
    return out