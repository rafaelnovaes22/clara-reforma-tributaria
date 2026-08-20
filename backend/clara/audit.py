from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import AgentState, ConversationScope
from .security import protected_identifier


class StructuredEventLogger:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def emit(self, level: str, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "event": event,
            **fields,
        }
        serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            print(serialized, flush=True)


class AuditRecorder:
    def __init__(self, logger: StructuredEventLogger, hash_key: str, path: Path | None, enabled: bool) -> None:
        self._logger = logger
        self._hash_key = hash_key
        self._path = path
        self._enabled = enabled
        self._file_lock = threading.Lock()

    def record_conversation(self, state: AgentState, scope: ConversationScope) -> None:
        record = self._base_record("conversation", state["run_id"], scope)
        record.update(
            {
                "intent": state.get("intent"),
                "source_ids": [source["id"] for source in state.get("evidence", [])],
                "risk": state.get("risk"),
                "generation_mode": state.get("generation_mode"),
                "human_review": state.get("needs_human_review"),
                "gates_passed": state.get("evals", {}).get("passed"),
            }
        )
        self._write(record)

    def record_policy_block(self, run_id: str, scope: ConversationScope, category: str, message: str) -> None:
        record = self._base_record("policy_block", run_id, scope)
        record["category"] = category
        record["content_hash"] = protected_identifier(message, self._hash_key)
        self._write(record)

    def record_document(self, run_id: str, scope: ConversationScope, finding_codes: list[str]) -> None:
        record = self._base_record("xml_triage", run_id, scope)
        record["finding_codes"] = finding_codes
        self._write(record)

    def _base_record(self, event: str, run_id: str, scope: ConversationScope) -> dict[str, Any]:
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "run_id": run_id,
            "actor": protected_identifier(scope.actor_id, self._hash_key),
            "client": protected_identifier(scope.client_id, self._hash_key),
            "session": protected_identifier(scope.session_id, self._hash_key),
        }

    def _write(self, record: dict[str, Any]) -> None:
        if not self._enabled:
            return
        self._logger.emit("info", "audit", audit=record)
        if self._path is None:
            return
        try:
            self._append_file(record)
        except OSError as exc:
            self._logger.emit("error", "audit_write_failed", error_type=type(exc).__name__)

    def _append_file(self, record: dict[str, Any]) -> None:
        assert self._path is not None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._file_lock, self._path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(serialized + "\n")
