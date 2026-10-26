"""
Redaction.

Two related guarantees:

1. **Structural redaction.** The ``Trace`` / ``StepTrace`` and the
   framework-generated ``Error.details`` never carry raw argument values,
   handler return values, or model prompts. This is by construction, not
   by regex.

2. **The ``redact`` helper.** Applications that place sensitive values in
   their own ``Error.details`` or elsewhere can call
   ``logix._internal.redaction.redact`` to strip default-sensitive keys,
   specific paths, or (opt-in) string patterns.

Honest limitation: Logix does NOT auto-redact arbitrary ``Error.details``
at ``to_dict()`` time — the framework-generated details contain no
secrets by construction, and application-supplied details are the
application's responsibility. The ``redact`` helper is the mechanism.
"""

from __future__ import annotations

import pytest

from logiq._internal.redaction import (
    DEFAULT_SENSITIVE_KEYS,
    REDACTED,
    Redactor,
    redact,
    redact_details,
)

# ---------------------------------------------------------------------------
# Structural redaction (traces never contain raw values)
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_trace_does_not_contain_argument_values(logix):
    secret = "sk-LIVE-SECRET-KEY-12345"

    @logix.capability
    def charge(api_key: str, amount: float) -> dict[str, int]:
        return {"ok": 1}

    result = logix.run(
        {
            "call": "charge",
            "with": {"api_key": secret, "amount": 5.0},
        }
    )
    assert result.ok
    # Trace serialization must not contain the raw key.
    import json

    trace_json = json.dumps(result.trace.to_dict())
    assert secret not in trace_json


@pytest.mark.security
def test_trace_does_not_contain_handler_return_value(logix):
    sensitive_return = "PII-SSN-999-99-9999"

    @logix.capability
    def get_user(user_id: int) -> str:
        return sensitive_return

    result = logix.run({"call": "get_user", "with": {"user_id": 1}})
    assert result.ok
    import json

    trace_json = json.dumps(result.trace.to_dict())
    assert sensitive_return not in trace_json


@pytest.mark.security
def test_framework_grounding_error_does_not_leak_value(logix):
    """GROUNDING_REQUIRED reports the *path*, not the value."""

    @logix.capability
    def refund(order_id: int, amount: float) -> dict[str, int]:
        return {"ok": 1}

    logix.grounding(require_ref_for=["refund.amount"])

    secret_amount = 42.195
    result = logix.run(
        {
            "call": "refund",
            "with": {"order_id": 1, "amount": secret_amount},
        }
    )
    assert not result.ok
    assert result.errors[0].code == "GROUNDING_REQUIRED"
    # The detail names the argument path, not the literal value.
    assert str(secret_amount) not in result.errors[0].message


# ---------------------------------------------------------------------------
# The redact() helper
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_redact_default_sensitive_keys():
    payload = {
        "user": "alice",
        "password": "hunter2",
        "nested": {"api_key": "sk-secret", "public": "ok"},
    }
    result = redact(payload)
    assert result["user"] == "alice"
    assert result["password"] == REDACTED
    assert result["nested"]["api_key"] == REDACTED
    assert result["nested"]["public"] == "ok"


@pytest.mark.security
def test_redact_is_case_insensitive_by_default():
    payload = {"PASSWORD": "x", "ApiKey": "y"}
    result = redact(payload)
    assert result["PASSWORD"] == REDACTED
    assert result["ApiKey"] == REDACTED


@pytest.mark.security
def test_redact_path_based():
    r = Redactor(
        sensitive_keys=frozenset(),
        redact_paths=frozenset({"user.pin"}),
    )
    payload = {"user": {"pin": "1234", "name": "alice"}}
    result = redact(payload, r)
    assert result["user"]["pin"] == REDACTED
    assert result["user"]["name"] == "alice"


@pytest.mark.security
def test_redact_preserves_structure():
    """Field names survive; only values become the sentinel."""
    payload = {"password": "x", "other": [1, 2]}
    result = redact(payload)
    assert set(result.keys()) == {"password", "other"}
    assert result["password"] == REDACTED
    assert result["other"] == [1, 2]


@pytest.mark.security
def test_redact_does_not_mutate_input():
    payload = {"password": "hunter2"}
    original = payload.copy()
    redact(payload)
    assert payload == original


@pytest.mark.security
def test_redact_with_patterns():
    import re

    r = Redactor(
        sensitive_keys=frozenset(),
        patterns=(re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),),
    )
    payload = {"note": "SSN is 123-45-6789, end."}
    result = redact(payload, r)
    assert "123-45-6789" not in result["note"]
    assert REDACTED in result["note"]


@pytest.mark.security
def test_redact_details_helper():
    details = {"api_key": "sk-x", "reason": "expired"}
    result = redact_details(details)
    assert result["api_key"] == REDACTED
    assert result["reason"] == "expired"


@pytest.mark.security
def test_default_sensitive_keys_covers_common_cases():
    """A sanity check that the default set includes common credential names."""
    for key in ("password", "token", "api_key", "secret", "authorization", "credit_card"):
        assert key in DEFAULT_SENSITIVE_KEYS


@pytest.mark.security
def test_no_default_patterns_applied_to_strings():
    """By default, free-form strings are NOT pattern-matched. This is a
    deliberate posture: false positives in diagnostics are worse than
    false negatives, and apps that know a field is free-text can opt in."""
    payload = {"note": "my password is hunter2"}
    result = redact(payload)
    # The key is "note" not "password" — the value is untouched.
    assert result["note"] == "my password is hunter2"
