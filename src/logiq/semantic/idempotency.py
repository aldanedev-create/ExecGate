"""
Idempotency: deduplicate side effects across retries.

The contract:

- A caller supplies an idempotency key per logical operation.
- ``check_and_reserve(key, args_hash)`` is called before the handler.
- ``commit(key, result)`` is called after success.
- ``release(key)`` is called on failure so a retry can reuse the key.

Three outcomes from ``check_and_reserve``:

- ``RESERVED``   — fresh key; proceed with handler invocation.
- ``REPLAY``     — key was already committed with the same args; the stored
                   result is returned and the handler is NOT invoked.
- ``CONFLICT``   — key was committed with different args, or is currently
                   reserved by an in-flight call; reject with
                   ``IDEMPOTENCY_CONFLICT``.

The in-memory store is best-effort. It does not survive process restarts
and cannot coordinate across processes. Applications that need durable
idempotency implement ``IdempotencyStore`` against their own store
(Redis, Postgres, DynamoDB).

See ``docs/semantic-layer.md`` and the spec's p.14 caveat about exactly-once.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class IdempotencyStatus(str, Enum):
    RESERVED = "reserved"
    REPLAY = "replay"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class IdempotencyResult:
    status: IdempotencyStatus
    cached_value: Any = None
    detail: str | None = None


class IdempotencyStore(Protocol):
    """
    The store protocol.

    Implementations must be atomic for a given key: two concurrent
    ``check_and_reserve`` calls for the same key with the same args must
    produce one ``RESERVED`` and one ``CONFLICT`` (in-progress). This is
    what prevents double side effects.
    """

    def check_and_reserve(self, key: str, args_hash: str) -> IdempotencyResult: ...
    def commit(self, key: str, result: Any) -> None: ...
    def release(self, key: str) -> None: ...


class InMemoryIdempotencyStore:
    """A single-process, thread-safe store. For tests and single-worker apps."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> ("reserved", args_hash) or ("committed", args_hash, value)
        self._entries: dict[str, tuple[Any, ...]] = {}

    def check_and_reserve(self, key: str, args_hash: str) -> IdempotencyResult:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = ("reserved", args_hash)
                return IdempotencyResult(IdempotencyStatus.RESERVED)
            state = entry[0]
            stored_hash = entry[1]
            if stored_hash != args_hash:
                return IdempotencyResult(
                    IdempotencyStatus.CONFLICT,
                    detail="idempotency key reused with different arguments",
                )
            if state == "reserved":
                return IdempotencyResult(
                    IdempotencyStatus.CONFLICT,
                    detail="idempotency key is reserved by an in-flight call",
                )
            # state == "committed", same args
            return IdempotencyResult(
                IdempotencyStatus.REPLAY,
                cached_value=entry[2],
            )

    def commit(self, key: str, result: Any) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry[0] != "reserved":
                # Committing an unknown or already-committed key is a bug in
                # the caller; do not overwrite.
                return
            self._entries[key] = ("committed", entry[1], result)

    def release(self, key: str) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] == "reserved":
                del self._entries[key]