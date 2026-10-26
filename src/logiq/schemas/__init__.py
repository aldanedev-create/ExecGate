"""
The native schema engine.

Public surface (stable 0.1)::

    from logiq.schemas import (
        ObjectType, IntType, StrType, BoolType, FloatType,
        ListType, DictType, LiteralType, UnionType, NoneType, AnyType, NumberType,
        ConstrainedType, Gt, Ge, Lt, Le, MinLength, MaxLength, Pattern,
        SchemaError, SchemaInferenceError,
        infer_input_schema, infer_output_schema,
        validate_input, validate_output,
        to_json_schema,
    )

What this package guarantees:

- The schema validator runs *before* any handler is invoked.
- Unsupported annotations fail loudly; no silent weakening.
- ``bool`` is not accepted where ``int`` is required.
- Unknown fields are rejected by default (``additionalProperties: false``).
- The same ``Type`` produces both validation and JSON Schema output, so
  the AI catalog and the verifier cannot disagree.
"""

from __future__ import annotations

from logiq.schemas.constraints import (
    Ge, Gt, Le, Lt, MaxLength, MinLength, Pattern,
)
from logiq.schemas.infer import (
    SchemaInferenceError, infer_input_schema, infer_output_schema,
)
from logiq.schemas.json_schema import capability_json_schema, to_json_schema
from logiq.schemas.types import (
    AnyType, BoolType, DictType, FloatType, IntType, ListType,
    LiteralType, NoneType, NumberType, ObjectType, SchemaError, StrType,
    Type, UnionType,
)
from logiq.schemas.unsupported import describe_unsupported
from logiq.schemas.validate import ConstrainedType, validate_input, validate_output

__all__ = [
    # types
    "AnyType", "BoolType", "DictType", "FloatType", "IntType",
    "ListType", "LiteralType", "NoneType", "NumberType", "ObjectType",
    "StrType",
    "Type", "UnionType",
    # constraints
    "Ge", "Gt", "Le", "Lt", "MaxLength", "MinLength", "Pattern",
    # validation
    "ConstrainedType", "SchemaError", "SchemaInferenceError",
    "validate_input", "validate_output",
    # inference
    "infer_input_schema", "infer_output_schema",
    # json schema
    "to_json_schema", "capability_json_schema",
    # diagnostics
    "describe_unsupported",
]