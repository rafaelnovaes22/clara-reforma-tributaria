from __future__ import annotations

import uuid
from itertools import pairwise
from typing import Any, Protocol

from .audit import AuditRecorder
from .contracts import AgentState, ConversationScope, ModelAnswer
from .dialogue import (
    classify_intent,
    detect_dialogue_act,
    extract_confirmed_facts,
    local_navigation_answer,
    requires_live_official_search,
    safe_abstention,
)
from .knowledge import load_source_registry, retrieve_sources
from .memory import BoundedConversationMemory
from .openai_client import OpenAIResponsesClient
from .security import RequestValidationError, detect_policy_violation, scoped_memory_key
from .settings import RuntimeSettings

try:
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False


SOUL_VERSION = "soul-clara-2026.08.20-v2"
POLICY_VERSION = "guardrails-rtc-2026.08.20-v5"
EVAL_SUITE_VERSION = "evals-pilot-rtc-2026.08.20-v4"
PROMPT_VERSIONS = {
    "orchestrator": "orchestrator-2026.08.20-v5",
    "tax_specialist": "tax-specialist-2026.08.20-v7",
    "reviewer": "reviewer-2026.08.20-v5",
}


class MaterialQuestionClient(Protocol):
    def answer_material_question(self, state: AgentState) -> ModelAnswer: ...


def append_trace(state: AgentState, agent: str, detail: str) -> list[dict[str, str]]:
    return [*state.get("trace", []), {"agent": agent, "status": "ok", "detail": detail}]


class ConversationEngine:
    def __init__(
        self,
        settings: RuntimeSettings,
        memory: BoundedConversationMemory,
        audit: AuditRecorder,
        model_client: MaterialQuestionClient | None = None,
    ) -> None:
        self.settings = settings
        self.memory = memory
        self.audit = audit
        self.sources = load_source_registry()
        self.model_client = model_client or OpenAIResponsesClient(settings)
        self.graph = self._build_graph()

    @property
    def graph_ready(self) -> bool:
        return LANGGRAPH_AVAILABLE and self.graph is not None

    def run_chat(self, message: str, scope: ConversationScope) -> dict[str, Any]:
        clean_message = message.strip()
        self._validate_message(clean_message)
        state = self._initial_state(clean_message, scope)
        violation = self._pre_model_violation(state)
        if violation:
            result = self._blocked_result(state, scope, violation)
            return self._public_response(result)
        result = self._invoke(state)
        self._persist_turn(result, scope)
        self.audit.record_conversation(result, scope)
        return self._public_response(result)

    def remember_document(self, scope: ConversationScope, summary: dict[str, Any]) -> None:
        memory_key = scoped_memory_key(scope.actor_id, scope.client_id, scope.session_id)
        self.memory.save_document(memory_key, scope.client_id, summary)

    def _validate_message(self, message: str) -> None:
        if not message:
            raise RequestValidationError("empty_message", "A pergunta não pode ficar vazia.")
        if len(message) > self.settings.max_message_chars:
            raise RequestValidationError(
                "message_too_large",
                f"A pergunta possui {len(message)} caracteres; o limite é {self.settings.max_message_chars}.",
            )

    def _initial_state(self, message: str, scope: ConversationScope) -> AgentState:
        memory_key = scoped_memory_key(scope.actor_id, scope.client_id, scope.session_id)
        record = self.memory.load(memory_key, scope.client_id)
        facts = dict(record.get("facts", {}))
        facts.update(extract_confirmed_facts(message))
        fibers = build_fibers(scope, record, facts)
        return {
            "run_id": str(uuid.uuid4()),
            "actor_id": scope.actor_id,
            "session_id": scope.session_id,
            "client_id": scope.client_id,
            "message": message,
            "history": record.get("turns", [])[-8:],
            "fibers": fibers,
            "trace": [
                {"agent": "Memória por fibras", "status": "ok", "detail": "Contexto recuperado no escopo autenticado"}
            ],
        }

    def _pre_model_violation(self, state: AgentState) -> str | None:
        previous_user_texts = [
            turn["content"] for turn in state.get("history", []) if turn.get("role") == "user" and turn.get("content")
        ]
        return detect_policy_violation([*previous_user_texts, state["message"]])

    def _blocked_result(self, state: AgentState, scope: ConversationScope, category: str) -> AgentState:
        state.update(blocked_state_update(state, category))
        self.audit.record_policy_block(state["run_id"], scope, category, state["message"])
        return state

    def _invoke(self, state: AgentState) -> AgentState:
        if self.graph is not None:
            return self.graph.invoke(state)
        for node in (self._orchestrate, self._retrieve, self._specialize, self._review, self._evaluate):
            state.update(node(state))
        return state

    def _persist_turn(self, state: AgentState, scope: ConversationScope) -> None:
        memory_key = scoped_memory_key(scope.actor_id, scope.client_id, scope.session_id)
        self.memory.save_turn(
            memory_key,
            scope.client_id,
            state["message"],
            state.get("answer", ""),
            extract_confirmed_facts(state["message"]),
            state.get("intent", "tax_question"),
        )

    def _orchestrate(self, state: AgentState) -> dict[str, Any]:
        record = state.get("fibers", {}).get("dialogue", {})
        dialogue_act = detect_dialogue_act(
            state["message"],
            state.get("history", []),
            state.get("fibers", {}).get("document"),
        )
        intent = classify_intent(state["message"], dialogue_act, record.get("last_intent"))
        return {
            "intent": intent,
            "dialogue_act": dialogue_act,
            "trace": append_trace(state, "Orquestrador", f"Intenção {intent}; ato {dialogue_act}"),
        }

    def _retrieve(self, state: AgentState) -> dict[str, Any]:
        if not requires_live_official_search(state):
            evidence = []
        else:
            history = " ".join(turn.get("content", "") for turn in state.get("history", [])[-4:])
            evidence = retrieve_sources(f"{history} {state['message']}", self.sources)
        return {
            "evidence": evidence,
            "trace": append_trace(state, "Pesquisa normativa", f"{len(evidence)} referências do catálogo encontradas"),
        }

    def _specialize(self, state: AgentState) -> dict[str, Any]:
        if not requires_live_official_search(state):
            answer = local_navigation_answer(state)
            return specialist_update(state, answer, "local_navigation", state.get("evidence", []), False)
        model_answer = self.model_client.answer_material_question(state)
        if model_answer.text is None:
            return specialist_update(state, safe_abstention(), "safe_abstention", [], True)
        return specialist_update(state, model_answer.text, model_answer.mode, model_answer.sources, False)

    def _review(self, state: AgentState) -> dict[str, Any]:
        material = requires_live_official_search(state)
        live_sources = [source for source in state.get("evidence", []) if source.get("live")]
        answer = state.get("draft", "")
        abstained = bool(state.get("abstained"))
        if material and not abstained and not live_sources:
            answer = safe_abstention()
            abstained = True
        if material and not abstained:
            answer = f"Rascunho para revisão obrigatória da contadora:\n\n{answer}"
        return reviewer_update(state, answer, material, abstained)

    def _evaluate(self, state: AgentState) -> dict[str, Any]:
        material = requires_live_official_search(state)
        live_evidence = any(source.get("live") for source in state.get("evidence", []))
        evidence_gate = not material or bool(state.get("abstained")) or live_evidence
        review_gate = not material or bool(state.get("needs_human_review"))
        gates = {
            "input_policy_handled": True,
            "official_evidence_or_abstention": evidence_gate,
            "mandatory_human_review": review_gate,
            "no_automatic_fiscal_approval": not material or state.get("risk") != "baixo",
        }
        passed = all(gates.values())
        evals = build_evaluation(gates, passed, live_evidence, bool(state.get("abstained")))
        return {
            "evals": evals,
            "trace": append_trace(state, "Avaliador", f"{sum(gates.values())}/{len(gates)} gates aprovados"),
        }

    def _build_graph(self) -> Any | None:
        if not LANGGRAPH_AVAILABLE:
            return None
        builder = StateGraph(AgentState)
        nodes = (
            ("orchestrator", self._orchestrate),
            ("retrieval", self._retrieve),
            ("specialist", self._specialize),
            ("review", self._review),
            ("evaluator", self._evaluate),
        )
        for name, node in nodes:
            builder.add_node(name, node)
        builder.add_edge(START, "orchestrator")
        for current, following in pairwise(nodes):
            builder.add_edge(current[0], following[0])
        builder.add_edge("evaluator", END)
        return builder.compile()

    def _public_response(self, state: AgentState) -> dict[str, Any]:
        return public_response(state)


def build_fibers(
    scope: ConversationScope,
    record: dict[str, Any],
    facts: dict[str, str],
) -> dict[str, Any]:
    return {
        "base": {"session_id": scope.session_id, "turns": len(record.get("turns", []))},
        "client": {"client_id": scope.client_id, "facts": facts},
        "regulatory": {"policy": "live-official-or-abstain", "jurisdiction": "Brasil"},
        "document": record.get("last_document"),
        "dialogue": {"last_intent": record.get("last_intent"), "active_topic": record.get("active_topic")},
    }


def specialist_update(
    state: AgentState,
    answer: str,
    mode: str,
    evidence: list[Any],
    abstained: bool,
) -> dict[str, Any]:
    return {
        "draft": answer,
        "generation_mode": mode,
        "evidence": evidence,
        "abstained": abstained,
        "trace": append_trace(state, "Especialista tributário", f"Modo {mode}"),
    }


def reviewer_update(state: AgentState, answer: str, material: bool, abstained: bool) -> dict[str, Any]:
    risk = "médio" if material else "baixo"
    checks = [
        {"name": "input policy", "passed": True},
        {
            "name": "evidência oficial ou abstenção",
            "passed": abstained or not material or any(source.get("live") for source in state.get("evidence", [])),
        },
        {"name": "revisão profissional", "passed": True, "required": material},
    ]
    return {
        "answer": answer,
        "risk": risk,
        "guardrails": checks,
        "needs_human_review": material,
        "abstained": abstained,
        "trace": append_trace(
            state, "Guardrails & revisão", f"Risco {risk}; revisão {'obrigatória' if material else 'não aplicável'}"
        ),
    }


def build_evaluation(
    gates: dict[str, bool],
    passed: bool,
    live_evidence: bool,
    abstained: bool,
) -> dict[str, Any]:
    score = round(sum(gates.values()) / len(gates), 2)
    grounding_status = "live_official" if live_evidence else "safe_abstention" if abstained else "not_applicable"
    return {
        "suite": EVAL_SUITE_VERSION,
        "overall": score,
        "passed": passed,
        "gates": gates,
        "grounding_status": grounding_status,
        "self_scored": False,
    }


def blocked_state_update(state: AgentState, category: str) -> dict[str, Any]:
    intent = classify_intent(state["message"], "question", None)
    gates = passed_guardrail_gates()
    return {
        "intent": intent,
        "dialogue_act": "blocked",
        "answer": blocked_answer(category),
        "generation_mode": "policy_block",
        "risk": "alto",
        "guardrails": [{"name": category, "passed": True, "action": "blocked"}],
        "needs_human_review": True,
        "blocked": True,
        "abstained": True,
        "evidence": [],
        "evals": build_evaluation(gates, True, False, True),
        "trace": append_trace(state, "Guardrails & revisão", f"Entrada bloqueada: {category}"),
    }


def blocked_answer(category: str) -> str:
    if category == "evasion":
        return "Não posso ajudar a burlar obrigações fiscais. Posso explicar caminhos legais de conformidade."
    return "Não posso revelar ou substituir instruções internas. Posso responder dentro do escopo tributário do piloto."


def passed_guardrail_gates() -> dict[str, bool]:
    return {
        "input_policy_handled": True,
        "official_evidence_or_abstention": True,
        "mandatory_human_review": True,
        "no_automatic_fiscal_approval": True,
    }


def public_response(state: AgentState) -> dict[str, Any]:
    return {
        "run_id": state["run_id"],
        "answer": state.get("answer", safe_abstention()),
        "intent": state.get("intent"),
        "dialogue_act": state.get("dialogue_act"),
        "generation_mode": state.get("generation_mode"),
        "risk": state.get("risk"),
        "needs_human_review": state.get("needs_human_review"),
        "blocked": state.get("blocked", False),
        "abstained": state.get("abstained", False),
        "sources": state.get("evidence", []),
        "trace": state.get("trace", []),
        "guardrails": state.get("guardrails", []),
        "evals": state.get("evals", {}),
        "governance": conversation_governance(),
    }


def conversation_governance() -> dict[str, Any]:
    return {
        "prompt_versions": PROMPT_VERSIONS,
        "soul_version": SOUL_VERSION,
        "policy_version": POLICY_VERSION,
        "memory_architecture": "authenticated bounded scope",
    }
