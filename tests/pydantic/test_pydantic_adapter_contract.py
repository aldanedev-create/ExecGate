"""
Pydantic adapter contract.

Two concerns:

1. ``transform_signature`` turns Pydantic model annotations (direct,
   inside ``Optional``/``list``/``dict``/``Union``) into ``PydanticType``
   instances that the native schema engine can handle.

2. ``PydanticType`` implements the full ``logix.schemas.Type`` protocol —
   ``validate``, ``to_json_schema``, ``walk`` — and normalizes handler
   I/O so ``Result.value`` stays JSON-safe and ``$ref`` traversal works.

Tests do not require FastMCP or any other integration. They exercise the
adapter through the public engine API.
"""

from __future__ import annotations

import json

import pytest

from execgate.annotation_inspect import find_unsupported_annotations, inspect_capability
from execgate.schemas import (
    DictType,
    FloatType,
    IntType,
    ListType,
    NoneType,
    StrType,
    UnionType,
    infer_input_schema,
    infer_output_schema,
)
from execgate.schemas.types import is_type_instance
from execgate_pydantic import (
    PydanticType,
    is_pydantic_model,
    model_to_json_schema,
    model_to_logix_type,
    normalize_validation_error,
    transform_signature,
)
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared models
# ---------------------------------------------------------------------------


class Address(BaseModel):
    city: str
    postcode: str


class Order(BaseModel):
    id: int
    total: float = Field(ge=0.0)
    address: Address


class LineItem(BaseModel):
    amount: float


# ---------------------------------------------------------------------------
# is_pydantic_model
# ---------------------------------------------------------------------------


def test_is_pydantic_model_positive():
    assert is_pydantic_model(Order)
    assert is_pydantic_model(Address)


def test_is_pydantic_model_rejects_instance():
    assert not is_pydantic_model(Order(id=1, total=0.0, address=Address(city="x", postcode="y")))


def test_is_pydantic_model_rejects_primitives():
    assert not is_pydantic_model(int)
    assert not is_pydantic_model(str)
    assert not is_pydantic_model(None)


# ---------------------------------------------------------------------------
# transform_signature — direct model
# ---------------------------------------------------------------------------


def test_transform_direct_model_parameter():
    def prepare(order: Order) -> dict[str, int]:
        return {"ok": 1}

    info = inspect_capability(prepare)
    transformed = transform_signature(info)

    order_param = next(p for p in transformed.parameters if p.name == "order")
    assert is_type_instance(order_param.annotation)
    assert isinstance(order_param.annotation, PydanticType)
    assert order_param.annotation.model_cls is Order


def test_transform_makes_signature_inferable():
    """Before transform, a Pydantic model is unsupported by the native
    inferencer. After transform, the whole signature passes."""

    def prepare(order: Order) -> dict[str, int]:
        return {"ok": 1}

    info = inspect_capability(prepare)
    assert find_unsupported_annotations(info) != []

    transformed = transform_signature(info)
    assert find_unsupported_annotations(transformed) == []
    schema = infer_input_schema(transformed.parameters)
    assert isinstance(schema.fields["order"], PydanticType)


def test_transform_preserves_non_model_annotations():
    def mixed(order: Order, note: str, count: int) -> dict[str, int]:
        return {"ok": 1}

    info = inspect_capability(mixed)
    transformed = transform_signature(info)

    by_name = {p.name: p.annotation for p in transformed.parameters}
    assert isinstance(by_name["order"], PydanticType)
    assert by_name["note"] is str
    assert by_name["count"] is int


# ---------------------------------------------------------------------------
# transform_signature — containers and unions
# ---------------------------------------------------------------------------


def test_transform_optional_model():
    def f(order: Order | None = None) -> dict[str, int]:
        return {"ok": 1}

    info = inspect_capability(f)
    transformed = transform_signature(info)

    ann = transformed.parameters[0].annotation
    assert isinstance(ann, UnionType)
    members = ann.members
    assert any(isinstance(m, PydanticType) for m in members)
    assert any(isinstance(m, NoneType) for m in members)


def test_transform_list_of_models():
    def f(orders: list[Order]) -> dict[str, int]:
        return {"ok": 1}

    info = inspect_capability(f)
    transformed = transform_signature(info)

    ann = transformed.parameters[0].annotation
    assert isinstance(ann, ListType)
    assert isinstance(ann.item_type, PydanticType)


def test_transform_dict_of_models():
    def f(by_id: dict[str, Order]) -> dict[str, int]:
        return {"ok": 1}

    info = inspect_capability(f)
    transformed = transform_signature(info)

    ann = transformed.parameters[0].annotation
    assert isinstance(ann, DictType)
    assert isinstance(ann.value_type, PydanticType)


def test_transform_union_of_models():
    def f(item: Order | Address) -> dict[str, int]:
        return {"ok": 1}

    info = inspect_capability(f)
    transformed = transform_signature(info)

    ann = transformed.parameters[0].annotation
    assert isinstance(ann, UnionType)
    assert len(ann.members) == 2
    assert all(isinstance(m, PydanticType) for m in ann.members)


# ---------------------------------------------------------------------------
# transform_signature — output
# ---------------------------------------------------------------------------


def test_transform_output_model():
    def op(x: int) -> Order:
        return Order(id=1, total=0.0, address=Address(city="x", postcode="y"))

    info = inspect_capability(op)
    transformed = transform_signature(info)
    output = infer_output_schema(transformed.return_annotation)
    assert isinstance(output, PydanticType)


# ---------------------------------------------------------------------------
# PydanticType.validate
# ---------------------------------------------------------------------------


def test_pydantic_type_validate_valid():
    pt = PydanticType(Order)
    assert (
        pt.validate(
            {
                "id": 1,
                "total": 5.0,
                "address": {"city": "x", "postcode": "y"},
            }
        )
        == []
    )


def test_pydantic_type_validate_invalid_type():
    pt = PydanticType(Order)
    errors = pt.validate(
        {
            "id": "not-an-int",
            "total": 5.0,
            "address": {"city": "x", "postcode": "y"},
        }
    )
    assert len(errors) >= 1
    # Path points into the field, not the whole object.
    assert any("id" in e.path for e in errors)


def test_pydantic_type_validate_missing_field():
    pt = PydanticType(Order)
    errors = pt.validate({"id": 1})  # missing total, address
    assert len(errors) >= 1


def test_pydantic_type_validate_constraint():
    pt = PydanticType(Order)
    errors = pt.validate(
        {
            "id": 1,
            "total": -1.0,  # violates ge=0.0
            "address": {"city": "x", "postcode": "y"},
        }
    )
    assert len(errors) >= 1


def test_pydantic_type_errors_drop_input_value():
    """Pydantic's ValidationError carries the raw input; the adapter must
    drop it (it may be sensitive)."""
    sensitive = "PII-987-65-4321"
    pt = PydanticType(Order)
    errors = pt.validate(
        {
            "id": sensitive,  # wrong type, contains PII
            "total": 5.0,
            "address": {"city": "x", "postcode": "y"},
        }
    )
    for e in errors:
        assert sensitive not in e.message


# ---------------------------------------------------------------------------
# PydanticType.to_json_schema
# ---------------------------------------------------------------------------


def test_pydantic_type_json_schema_matches_model():
    pt = PydanticType(Order)
    assert pt.to_json_schema() == model_to_json_schema(Order)


def test_model_to_logix_type_returns_pydantic_type():
    pt = model_to_logix_type(Order)
    assert isinstance(pt, PydanticType)
    assert pt.model_cls is Order


# ---------------------------------------------------------------------------
# PydanticType.walk
# ---------------------------------------------------------------------------


def test_walk_simple_field():
    pt = PydanticType(Order)
    assert pt.walk("id") == IntType()
    assert pt.walk("total") == FloatType()


def test_walk_nested_model():
    pt = PydanticType(Order)
    nested = pt.walk("address")
    assert isinstance(nested, PydanticType)
    assert nested.model_cls is Address
    # And we can walk deeper.
    assert nested.walk("city") == StrType()


def test_walk_unknown_field_returns_none():
    pt = PydanticType(Order)
    assert pt.walk("nonexistent") is None


def test_walk_optional_field():
    class Maybe(BaseModel):
        maybe: int | None = None

    pt = PydanticType(Maybe)
    # Optional unwrapped to the non-None type.
    assert pt.walk("maybe") == IntType()


def test_walk_list_of_models_returns_none():
    """Documented limitation: ``walk`` can't traverse a field whose type
    is a list of Pydantic models — the annotation is not natively
    inferable. A ``$ref`` into ``items.0.amount`` would be rejected at
    verify time. Applications that need this should declare the model's
    fields as plain JSON via a schema adapter."""

    class OrderWithItems(BaseModel):
        items: list[LineItem]

    pt = PydanticType(OrderWithItems)
    assert pt.walk("items") is None


# ---------------------------------------------------------------------------
# normalize_validation_error
# ---------------------------------------------------------------------------


def test_normalize_validation_error():
    pt = PydanticType(Order)
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        # Force a pydantic.ValidationError by direct adapter call.
        pt._adapter.validate_python({"id": "bad"})
    try:
        pt._adapter.validate_python({"id": "bad"})
    except Exception as e:
        dicts = normalize_validation_error(e)
        assert isinstance(dicts, list)
        assert all("path" in d and "message" in d for d in dicts)


# ---------------------------------------------------------------------------
# End-to-end through the engine
# ---------------------------------------------------------------------------


def test_register_with_model_and_run(logix):
    received: list[Order] = []

    @logix.capability
    def prepare(order: Order) -> dict[str, int]:
        received.append(order)
        return {"ok": 1}

    result = logix.run(
        {
            "call": "prepare",
            "with": {
                "order": {
                    "id": 1,
                    "total": 5.0,
                    "address": {"city": "x", "postcode": "y"},
                },
            },
        }
    )
    assert result.ok
    assert len(received) == 1
    assert isinstance(received[0], Order)  # MODEL mode is the default
    assert received[0].id == 1


def test_invalid_model_input_rejected_before_handler(logix):
    invoked: list[int] = []

    @logix.capability
    def prepare(order: Order) -> dict[str, int]:
        invoked.append(1)
        return {"ok": 1}

    result = logix.run(
        {
            "call": "prepare",
            "with": {"order": {"id": "not-an-int"}},
        }
    )
    assert not result.ok
    assert result.errors[0].code == "SCHEMA_VALIDATION_FAILED"
    assert invoked == []


def test_pydantic_output_normalized_to_dict(logix):
    @logix.capability
    def op(x: int) -> Address:
        return Address(city="Berlin", postcode="10115")

    result = logix.run({"call": "op", "with": {"x": 1}})
    assert result.ok
    assert isinstance(result.value, dict)
    assert result.value == {"city": "Berlin", "postcode": "10115"}
    # JSON-safe.
    json.dumps(result.value)


def test_ref_into_pydantic_typed_output(logix):
    """$ref into a step whose output schema is a Pydantic model works
    because (a) walk resolves the field and (b) the executor normalizes
    the model to a dict before storing it in step_outputs."""

    @logix.capability
    def get_order(order_id: int) -> Order:
        return Order(
            id=order_id,
            total=50.0,
            address=Address(city="x", postcode="y"),
        )

    @logix.capability
    def refund(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "o", "call": "get_order", "with": {"order_id": 1}},
                {
                    "id": "r",
                    "call": "refund",
                    "with": {"order_id": {"$ref": "o.id"}, "amount": {"$ref": "o.total"}},
                },
            ],
        }
    )
    assert result.ok, result.errors
    assert result.value["r"] == {"ok": 1}


def test_ref_into_nested_pydantic_field(logix):
    @logix.capability
    def get_order(order_id: int) -> Order:
        return Order(
            id=order_id,
            total=50.0,
            address=Address(city="Berlin", postcode="10115"),
        )

    @logix.capability
    def note(city: str) -> dict[str, int]:
        return {"ok": 1}

    result = logix.run(
        {
            "version": "1",
            "steps": [
                {"id": "o", "call": "get_order", "with": {"order_id": 1}},
                {"id": "n", "call": "note", "with": {"city": {"$ref": "o.address.city"}}},
            ],
        }
    )
    assert result.ok, result.errors
