from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .audit import AuditRecorder, StructuredEventLogger
from .contracts import ConversationScope, SourceRecord
from .conversation import (
    EVAL_SUITE_VERSION,
    POLICY_VERSION,
    PROMPT_VERSIONS,
    SOUL_VERSION,
    ConversationEngine,
)
from .knowledge import SOURCE_REGISTRY_PATH, source_registry_is_fresh
from .memory import BoundedConversationMemory
from .security import SlidingWindowRateLimiter
from .sessions import PilotSession, PilotSessionRegistry
from .settings import PROJECT_ROOT, RuntimeSettings

SCENARIOS = [
    "Qual é o cronograma vigente da NF-e para este regime?",
    "Pesquise como o split payment pode afetar o fluxo de caixa.",
    "Faça a triagem de um XML sintético.",
]
REQUIRED_FILES = (
    PROJECT_ROOT / "frontend" / "index.html",
    PROJECT_ROOT / "frontend" / "app.js",
    PROJECT_ROOT / "frontend" / "styles.css",
    PROJECT_ROOT / "SOUL.md",
    PROJECT_ROOT / "data" / "prompt_registry.json",
    PROJECT_ROOT / "data" / "risk_register.json",
    SOURCE_REGISTRY_PATH,
)


@dataclass(frozen=True, slots=True)
class _ApplicationRateLimiters:
    global_rate: SlidingWindowRateLimiter
    actor_rate: SlidingWindowRateLimiter
    chat_rate: SlidingWindowRateLimiter
    xml_rate: SlidingWindowRateLimiter
    auth_failure_rate: SlidingWindowRateLimiter


@dataclass(frozen=True, slots=True)
class _ReadinessSnapshot:
    required_files: bool
    source_registry_fresh: bool
    version_registry: bool
    audit_destination: bool


@dataclass(frozen=True, slots=True)
class _ApplicationDependencies:
    settings: RuntimeSettings
    logger: StructuredEventLogger
    audit: AuditRecorder
    memory: BoundedConversationMemory
    sessions: PilotSessionRegistry
    conversation: ConversationEngine
    rate_limiters: _ApplicationRateLimiters


def _create_audit_recorder(settings: RuntimeSettings, logger: StructuredEventLogger) -> AuditRecorder:
    return AuditRecorder(
        logger,
        settings.audit_hash_key,
        settings.audit_path,
        settings.audit_enabled,
    )


def _create_session_registry(settings: RuntimeSettings) -> PilotSessionRegistry:
    return PilotSessionRegistry(
        settings.pilot_client_id,
        settings.max_sessions,
        secure_cookie=settings.environment == "pilot",
    )


def _create_rate_limiters(settings: RuntimeSettings) -> _ApplicationRateLimiters:
    return _ApplicationRateLimiters(
        global_rate=SlidingWindowRateLimiter(max(60, settings.max_requests_per_minute * 10)),
        actor_rate=SlidingWindowRateLimiter(settings.max_requests_per_minute),
        chat_rate=SlidingWindowRateLimiter(settings.max_chat_requests_per_minute),
        xml_rate=SlidingWindowRateLimiter(5),
        auth_failure_rate=SlidingWindowRateLimiter(10, window_seconds=300),
    )


def _create_application_dependencies(settings: RuntimeSettings) -> _ApplicationDependencies:
    logger = StructuredEventLogger()
    audit = _create_audit_recorder(settings, logger)
    memory = BoundedConversationMemory(settings.max_sessions)
    return _ApplicationDependencies(
        settings=settings,
        logger=logger,
        audit=audit,
        memory=memory,
        sessions=_create_session_registry(settings),
        conversation=ConversationEngine(settings, memory, audit),
        rate_limiters=_create_rate_limiters(settings),
    )


def _create_application(
    application_type: type[ClaraApplication],
    dependencies: _ApplicationDependencies,
) -> ClaraApplication:
    rates = dependencies.rate_limiters
    return application_type(
        settings=dependencies.settings,
        logger=dependencies.logger,
        audit=dependencies.audit,
        memory=dependencies.memory,
        sessions=dependencies.sessions,
        conversation=dependencies.conversation,
        sources=dependencies.conversation.sources,
        global_rate=rates.global_rate,
        actor_rate=rates.actor_rate,
        chat_rate=rates.chat_rate,
        xml_rate=rates.xml_rate,
        auth_failure_rate=rates.auth_failure_rate,
    )


@dataclass(slots=True)
class ClaraApplication:
    settings: RuntimeSettings
    logger: StructuredEventLogger
    audit: AuditRecorder
    memory: BoundedConversationMemory
    sessions: PilotSessionRegistry
    conversation: ConversationEngine
    sources: list[SourceRecord]
    global_rate: SlidingWindowRateLimiter
    actor_rate: SlidingWindowRateLimiter
    chat_rate: SlidingWindowRateLimiter
    xml_rate: SlidingWindowRateLimiter
    auth_failure_rate: SlidingWindowRateLimiter

    @classmethod
    def build(cls, settings: RuntimeSettings | None = None) -> ClaraApplication:
        active_settings = settings or RuntimeSettings.from_environment()
        dependencies = _create_application_dependencies(active_settings)
        return _create_application(cls, dependencies)

    def scope(self, session: PilotSession) -> ConversationScope:
        return ConversationScope(session.actor_id, session.client_id, session.session_id)

    def source(self, source_id: str) -> SourceRecord:
        source = next((item for item in self.sources if item["id"] == source_id), None)
        if source is None:
            raise RuntimeError(f"Fonte obrigatória não encontrada: {source_id}.")
        return source

    def readiness(self, today: date | None = None) -> tuple[bool, dict[str, Any]]:
        current_date = today or date.today()
        snapshot = _collect_readiness_snapshot(self, current_date)
        failures = self.settings.readiness_failures(
            self.conversation.graph_ready,
            source_registry_ready=snapshot.source_registry_fresh,
            required_files_ready=snapshot.required_files and snapshot.version_registry,
            audit_destination_ready=snapshot.audit_destination,
        )
        ready = not failures
        return ready, _readiness_payload(snapshot, self.conversation.graph_ready, ready)


def _collect_readiness_snapshot(application: ClaraApplication, current_date: date) -> _ReadinessSnapshot:
    sources_ready = source_registry_is_fresh(
        application.sources,
        current_date,
        application.settings.source_max_age_days,
    )
    return _ReadinessSnapshot(
        required_files=all(path.is_file() for path in REQUIRED_FILES),
        source_registry_fresh=sources_ready,
        version_registry=prompt_registry_matches_code(PROJECT_ROOT / "data" / "prompt_registry.json"),
        audit_destination=audit_destination_is_ready(application.settings),
    )


def _readiness_payload(snapshot: _ReadinessSnapshot, graph_ready: bool, ready: bool) -> dict[str, Any]:
    return {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "configuration": ready,
            "required_files": snapshot.required_files,
            "source_registry_fresh": snapshot.source_registry_fresh,
            "version_registry": snapshot.version_registry,
            "graph": graph_ready,
            "audit_destination": snapshot.audit_destination,
        },
    }


def prompt_registry_matches_code(path: Path) -> bool:
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
        registered_ids = {item["id"] for item in registry["prompts"]}
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return False
    expected_ids = {*PROMPT_VERSIONS.values(), SOUL_VERSION}
    return expected_ids.issubset(registered_ids)


def governance_manifest() -> dict[str, Any]:
    return {
        "prompts": PROMPT_VERSIONS,
        "soul": SOUL_VERSION,
        "policy": POLICY_VERSION,
        "evals": EVAL_SUITE_VERSION,
    }


def audit_destination_is_ready(settings: RuntimeSettings) -> bool:
    if not settings.audit_enabled or settings.audit_path is None:
        return settings.audit_enabled
    target = settings.audit_path if settings.audit_path.exists() else settings.audit_path.parent
    return target.exists() and os.access(target, os.W_OK)
