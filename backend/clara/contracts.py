from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict


class SourceRecord(TypedDict):
    id: str
    title: str
    issuer: str
    published_at: str
    updated_at: str
    effective_from: str
    effective_to: str | None
    reviewed_at: str
    url: str
    tags: list[str]
    excerpt: str
    supports_claims: list[str]
    live: bool
    retrieved_at: NotRequired[str]


class AgentState(TypedDict, total=False):
    run_id: str
    actor_id: str
    session_id: str
    client_id: str
    message: str
    history: list[dict[str, str]]
    intent: str
    dialogue_act: str
    fibers: dict[str, Any]
    evidence: list[SourceRecord]
    trace: list[dict[str, str]]
    draft: str
    generation_mode: str
    answer: str
    risk: str
    guardrails: list[dict[str, Any]]
    evals: dict[str, Any]
    needs_human_review: bool
    blocked: bool
    abstained: bool


@dataclass(frozen=True, slots=True)
class ConversationScope:
    actor_id: str
    client_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class ModelAnswer:
    text: str | None
    mode: str
    sources: list[SourceRecord]
    failure_code: str | None = None
