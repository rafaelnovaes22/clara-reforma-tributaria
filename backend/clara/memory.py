from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


class BoundedConversationMemory:
    def __init__(
        self,
        max_sessions: int,
        ttl_seconds: int = 7_200,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._last_seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def load(self, memory_key: str, client_id: str) -> dict[str, Any]:
        with self._lock:
            self._purge_expired()
            record = self._records.get(memory_key)
            if record is None:
                return {"turns": [], "client_id": client_id, "facts": {}}
            self._touch(memory_key)
            return copy.deepcopy(record)

    def save_turn(
        self,
        memory_key: str,
        client_id: str,
        user_message: str,
        assistant_message: str,
        facts: dict[str, str],
        intent: str,
    ) -> None:
        with self._lock:
            self._purge_expired()
            conversation_record = self._get_or_create_record(memory_key, client_id)
            self._append_turn_pair(conversation_record, user_message, assistant_message)
            conversation_record["facts"].update(facts)
            conversation_record["last_intent"] = intent
            conversation_record["active_topic"] = intent
            self._touch_and_trim(memory_key)

    def save_document(self, memory_key: str, client_id: str, summary: dict[str, Any]) -> None:
        with self._lock:
            self._purge_expired()
            conversation_record = self._get_or_create_record(memory_key, client_id)
            conversation_record["last_document"] = copy.deepcopy(summary)
            conversation_record["last_intent"] = "invoice"
            conversation_record["active_topic"] = "invoice"
            self._touch_and_trim(memory_key)

    def snapshot(self, memory_key: str) -> dict[str, Any]:
        with self._lock:
            self._purge_expired()
            return copy.deepcopy(self._records.get(memory_key, {}))

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._last_seen.clear()

    def delete(self, memory_key: str) -> None:
        with self._lock:
            self._records.pop(memory_key, None)
            self._last_seen.pop(memory_key, None)

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired()
            return len(self._records)

    def _get_or_create_record(self, memory_key: str, client_id: str) -> dict[str, Any]:
        return self._records.setdefault(
            memory_key,
            {"turns": [], "client_id": client_id, "facts": {}},
        )

    def _append_turn_pair(
        self,
        conversation_record: dict[str, Any],
        user_message: str,
        assistant_message: str,
    ) -> None:
        conversation_record["turns"].extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]
        )
        conversation_record["turns"] = conversation_record["turns"][-12:]

    def _touch_and_trim(self, memory_key: str) -> None:
        self._touch(memory_key)
        while len(self._records) > self._max_sessions:
            evicted_key, _ = self._records.popitem(last=False)
            self._last_seen.pop(evicted_key, None)

    def _touch(self, memory_key: str) -> None:
        self._records.move_to_end(memory_key)
        self._last_seen[memory_key] = self._clock()

    def _purge_expired(self) -> None:
        cutoff = self._clock() - self._ttl_seconds
        expired = [key for key, last_seen in self._last_seen.items() if last_seen <= cutoff]
        for memory_key in expired:
            self._records.pop(memory_key, None)
            self._last_seen.pop(memory_key, None)
