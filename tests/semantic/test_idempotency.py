"""
Idempotency: the in-memory store and end-to-end executor integration.

The store is single-process, thread-safe, and best-effort. Applications
that need durability implement their own ``IdempotencyStore`` — the
protocol is the contract; this class is the default.
"""

from __future__ import annotations

from execgate import Logix
from execgate.semantic import (
    IdempotencyStatus,
    InMemoryIdempotencyStore,
)

# ---------------------------------------------------------------------------
# InMemoryIdempotencyStore: direct
# ---------------------------------------------------------------------------


def test_fresh_key_reserves():
    store = InMemoryIdempotencyStore()
    result = store.check_and_reserve("k", "hash")
    assert result.status is IdempotencyStatus.RESERVED


def test_after_commit_replay():
    store = InMemoryIdempotencyStore()
    store.check_and_reserve("k", "hash")
    store.commit("k", {"value": 42})

    result = store.check_and_reserve("k", "hash")
    assert result.status is IdempotencyStatus.REPLAY
    assert result.cached_value == {"value": 42}


def test_different_hash_after_commit_conflicts():
    store = InMemoryIdempotencyStore()
    store.check_and_reserve("k", "hash1")
    store.commit("k", "old")

    result = store.check_and_reserve("k", "hash2")
    assert result.status is IdempotencyStatus.CONFLICT
    assert "different arguments" in (result.detail or "")


def test_reserved_not_committed_conflicts():
    """Simulates an in-flight call: reserved but not yet committed."""
    store = InMemoryIdempotencyStore()
    store.check_and_reserve("k", "hash")

    result = store.check_and_reserve("k", "hash")
    assert result.status is IdempotencyStatus.CONFLICT
    assert "in-flight" in (result.detail or "")


def test_release_reserved_allows_new_reservation():
    store = InMemoryIdempotencyStore()
    store.check_and_reserve("k", "hash")
    store.release("k")

    result = store.check_and_reserve("k", "hash")
    assert result.status is IdempotencyStatus.RESERVED


def test_release_committed_is_noop():
    store = InMemoryIdempotencyStore()
    store.check_and_reserve("k", "hash")
    store.commit("k", "value")
    store.release("k")  # no-op

    result = store.check_and_reserve("k", "hash")
    assert result.status is IdempotencyStatus.REPLAY
    assert result.cached_value == "value"


def test_commit_unknown_key_noop():
    store = InMemoryIdempotencyStore()
    store.commit("unknown", "value")  # must not raise
    # Unknown key was not stored; next reserve succeeds.
    assert store.check_and_reserve("unknown", "h").status is IdempotencyStatus.RESERVED


def test_commit_already_committed_keeps_old_value():
    store = InMemoryIdempotencyStore()
    store.check_and_reserve("k", "hash")
    store.commit("k", "first")
    store.commit("k", "second")  # no-op

    result = store.check_and_reserve("k", "hash")
    assert result.cached_value == "first"


# ---------------------------------------------------------------------------
# End-to-end via Logix
# ---------------------------------------------------------------------------


def test_idempotent_capability_handler_once(logix):
    calls = []

    @logix.capability(idempotent=True)
    def charge(order_id: int, amount: float) -> dict[str, int]:
        calls.append(order_id)
        return {"ok": 1}

    r1 = logix.run({"call": "charge", "with": {"order_id": 1, "amount": 5.0}})
    r2 = logix.run({"call": "charge", "with": {"order_id": 1, "amount": 5.0}})

    assert r1.ok and r2.ok
    assert r1.value == r2.value
    assert len(calls) == 1


def test_idempotent_different_args_invokes_twice(logix):
    calls = []

    @logix.capability(idempotent=True)
    def charge(order_id: int, amount: float) -> dict[str, int]:
        calls.append(order_id)
        return {"ok": 1}

    logix.run({"call": "charge", "with": {"order_id": 1, "amount": 5.0}})
    logix.run({"call": "charge", "with": {"order_id": 2, "amount": 5.0}})
    assert len(calls) == 2


def test_non_idempotent_invokes_every_time(logix):
    calls = []

    @logix.capability
    def charge(order_id: int, amount: float) -> dict[str, int]:
        calls.append(order_id)
        return {"ok": 1}

    logix.run({"call": "charge", "with": {"order_id": 1, "amount": 5.0}})
    logix.run({"call": "charge", "with": {"order_id": 1, "amount": 5.0}})
    assert len(calls) == 2


def test_idempotent_release_on_handler_failure(logix):
    """First attempt fails, second succeeds — reservation was released."""
    calls = []
    attempt = [0]

    @logix.capability(idempotent=True)
    def charge(order_id: int) -> dict[str, int]:
        calls.append(order_id)
        attempt[0] += 1
        if attempt[0] == 1:
            raise ValueError("temporary failure")
        return {"ok": 1}

    r1 = logix.run({"call": "charge", "with": {"order_id": 1}})
    assert not r1.ok
    assert r1.errors[0].code == "HANDLER_FAILED"

    r2 = logix.run({"call": "charge", "with": {"order_id": 1}})
    assert r2.ok
    assert len(calls) == 2


def test_idempotent_release_on_output_validation_failure(logix):
    """First attempt returns bad output, second succeeds."""
    calls = []
    attempt = [0]

    @logix.capability(idempotent=True)
    def charge(order_id: int) -> dict[str, int]:
        calls.append(order_id)
        attempt[0] += 1
        if attempt[0] == 1:
            return "wrong type"  # type: ignore[return-value]
        return {"ok": 1}

    r1 = logix.run({"call": "charge", "with": {"order_id": 1}})
    assert not r1.ok
    assert r1.errors[0].code == "OUTPUT_VALIDATION_FAILED"

    r2 = logix.run({"call": "charge", "with": {"order_id": 1}})
    assert r2.ok
    assert len(calls) == 2


def test_two_engines_isolated_idempotency():
    """Two engines each have their own store — no cross-contamination."""
    a = Logix()
    b = Logix()
    calls_a = []
    calls_b = []

    def make(calls, tag):
        def charge(order_id: int) -> dict[str, str]:
            calls.append(tag)
            return {"tag": tag}

        return charge

    a.capability.register(make(calls_a, "a"), name="charge", idempotent=True)
    b.capability.register(make(calls_b, "b"), name="charge", idempotent=True)

    a.run({"call": "charge", "with": {"order_id": 1}})
    b.run({"call": "charge", "with": {"order_id": 1}})

    assert calls_a == ["a"]
    assert calls_b == ["b"]
