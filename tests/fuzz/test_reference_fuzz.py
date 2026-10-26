"""
Property-based tests for ``plans.references``.

Two functions with explicit contracts:

    parse_reference(value) -> Reference | Error

    resolve_reference(ref: Reference, results: dict) -> Any | Error

Both must never raise for any input whose type matches the annotation.
``parse_reference`` must round-trip valid ``$ref`` values through
``Reference.as_string()``. ``resolve_reference`` must return ``Error``
(never raise) for every "not found" case.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from execgate.errors import Error
from execgate.plans.references import (
    Reference,
    is_reference,
    parse_reference,
    resolve_reference,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A legal step identifier: matches ``[A-Za-z_][A-Za-z0-9_]*``.
_identifier = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,20}", fullmatch=True)

# A path segment: matches either ``[A-Za-z_][A-Za-z0-9_]*`` or ``\d+``.
_path_segment = st.one_of(
    st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,15}", fullmatch=True),
    st.integers(min_value=0, max_value=10**6).map(str),
)


@st.composite
def _valid_ref_dict(draw):
    step_id = draw(_identifier)
    n_segments = draw(st.integers(min_value=0, max_value=3))
    segments = [draw(_path_segment) for _ in range(n_segments)]
    ref_string = step_id + ("." + ".".join(segments) if segments else "")
    return {"$ref": ref_string}


# Arbitrary JSON-compatible values (what parse_reference might receive).
_json_values = st.recursive(
    st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=20)),
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(st.text(max_size=10), children, max_size=3),
    ),
    max_leaves=10,
)


# Results dict mapping step ids to values of various shapes.
_results_value = st.recursive(
    st.one_of(st.integers(), st.text(max_size=10), st.booleans()),
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(st.text(max_size=8), children, max_size=3),
    ),
    max_leaves=8,
)

_results_dict = st.dictionaries(_identifier, _results_value, max_size=5)


# ---------------------------------------------------------------------------
# parse_reference: never crashes, always returns Reference or Error
# ---------------------------------------------------------------------------


@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(value=_json_values)
def test_parse_reference_never_crashes(value):
    """Any JSON-compatible input produces Reference or Error, nothing else."""
    result = parse_reference(value)
    assert isinstance(result, (Reference, Error)), (
        f"parse_reference returned {type(result).__name__}"
    )
    if isinstance(result, Error):
        assert result.code == "INVALID_REFERENCE"


# ---------------------------------------------------------------------------
# parse_reference: valid refs round-trip
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(ref_dict=_valid_ref_dict())
def test_valid_ref_round_trips(ref_dict):
    """A valid ``{"$ref": "..."}`` parses to a Reference and reconstructs
    to the same string via ``as_string()``."""
    result = parse_reference(ref_dict)
    assert isinstance(result, Reference), (
        f"valid $ref {ref_dict!r} rejected: {result.message if isinstance(result, Error) else '?'}"
    )
    assert result.as_string() == ref_dict["$ref"]


@settings(max_examples=200, deadline=None)
@given(ref_dict=_valid_ref_dict())
def test_is_reference_true_for_valid(ref_dict):
    assert is_reference(ref_dict) is True


# ---------------------------------------------------------------------------
# parse_reference: structurally invalid refs always produce Error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_input",
    [
        None,
        True,
        False,
        0,
        1,
        -1,
        0.0,
        "",
        "string",
        [],
        [1, 2],
        {},
        {"not_ref": "x"},
        {"$ref": None},
        {"$ref": 42},
        {"$ref": ""},
        {"$ref": "a", "extra": 1},  # extra keys = not a reference
        {"$ref": "123bad"},  # invalid step id
        {"$ref": "a."},  # trailing empty segment
        {"$ref": ".a"},  # leading empty segment
        {"$ref": "a..b"},  # empty segment in middle
        {"$ref": "a.b-c"},  # invalid segment characters
        {"$ref": "a.!"},  # invalid segment
    ],
)
def test_invalid_ref_rejected(bad_input):
    result = parse_reference(bad_input)
    assert isinstance(result, Error), (
        f"malformed $ref {bad_input!r} unexpectedly accepted as {type(result).__name__}"
    )
    assert result.code == "INVALID_REFERENCE"


# ---------------------------------------------------------------------------
# resolve_reference: never crashes for valid input types
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    step_id=_identifier,
    path=st.lists(_path_segment, max_size=3),
    results=_results_dict,
)
def test_resolve_reference_never_crashes(step_id, path, results):
    """A parsed Reference and any results dict — never raises."""
    ref = Reference(step_id=step_id, path=tuple(path))
    result = resolve_reference(ref, results)
    # Result is either a value (any type) or an Error.
    if isinstance(result, Error):
        assert result.code == "INVALID_REFERENCE"


# ---------------------------------------------------------------------------
# resolve_reference: missing step always yields Error
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    step_id=_identifier,
    path=st.lists(_path_segment, max_size=2),
)
def test_resolve_missing_step_returns_error(step_id, path):
    ref = Reference(step_id=step_id, path=tuple(path))
    result = resolve_reference(ref, {})  # empty results
    assert isinstance(result, Error)
    assert result.code == "INVALID_REFERENCE"


# ---------------------------------------------------------------------------
# resolve_reference: successful paths return the value
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    value=_results_value,
    step_id=_identifier,
)
def test_resolve_identity_path_returns_value(value, step_id):
    """A Reference with empty path returns the step's top-level result."""
    ref = Reference(step_id=step_id, path=())
    result = resolve_reference(ref, {step_id: value})
    assert result == value


@settings(max_examples=100, deadline=None)
@given(
    key=st.text(min_size=1, max_size=10),
    value=_results_value,
    step_id=_identifier,
)
def test_resolve_dict_key_returns_value(key, value, step_id):
    """A single-segment path into a dict returns that key's value."""
    ref = Reference(step_id=step_id, path=(key,))
    result = resolve_reference(ref, {step_id: {key: value}})
    assert result == value


@settings(max_examples=100, deadline=None)
@given(
    index=st.integers(min_value=0, max_value=50),
    value=_results_value,
    step_id=_identifier,
)
def test_resolve_list_index_returns_value(index, value, step_id):
    """A numeric segment into a list returns that index's value."""
    ref = Reference(step_id=step_id, path=(str(index),))
    result = resolve_reference(ref, {step_id: [value] * (index + 1)})
    assert result == value


# ---------------------------------------------------------------------------
# resolve_reference: missing key/index always yields Error
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    key=st.text(min_size=1, max_size=10),
    step_id=_identifier,
)
def test_resolve_missing_key_returns_error(key, step_id):
    # Deliberately choose a different key in the dict.
    other_key = key + "_x"
    if other_key == key:
        return
    ref = Reference(step_id=step_id, path=(key,))
    result = resolve_reference(ref, {step_id: {other_key: 1}})
    assert isinstance(result, Error)


@settings(max_examples=100, deadline=None)
@given(
    index=st.integers(min_value=1, max_value=100),
    step_id=_identifier,
)
def test_resolve_out_of_range_index_returns_error(index, step_id):
    ref = Reference(step_id=step_id, path=(str(index),))
    result = resolve_reference(ref, {step_id: [0] * index})  # len == index
    assert isinstance(result, Error)
    assert "out of range" in result.message


@settings(max_examples=100, deadline=None)
@given(
    segment=st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,10}", fullmatch=True),
    step_id=_identifier,
)
def test_resolve_non_numeric_segment_on_list_returns_error(segment, step_id):
    """A path segment that isn't an integer cannot descend into a list."""
    ref = Reference(step_id=step_id, path=(segment,))
    result = resolve_reference(ref, {step_id: [1, 2, 3]})
    assert isinstance(result, Error)
    assert "integer index" in result.message


@settings(max_examples=100, deadline=None)
@given(
    scalar=st.one_of(st.integers(), st.text(max_size=10), st.booleans()),
    segment=_path_segment,
    step_id=_identifier,
)
def test_resolve_descend_into_scalar_returns_error(scalar, segment, step_id):
    """A scalar has no keys or indices — descending returns Error."""
    ref = Reference(step_id=step_id, path=(segment,))
    result = resolve_reference(ref, {step_id: scalar})
    assert isinstance(result, Error)
