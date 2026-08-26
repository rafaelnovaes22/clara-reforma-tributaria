from __future__ import annotations

import re
from typing import Any

from .contracts import AgentState

MATERIAL_INTENTS = {"invoice", "split_payment", "tax_question"}
UF_PATTERN = r"\b(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b"
LOCAL_DIALOGUE_ACTS = {
    "greeting",
    "closing",
    "provide_data",
    "vague_without_context",
    "short_reply",
    "document_follow_up",
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


def extract_confirmed_facts(text: str) -> dict[str, str]:
    normalized = normalize_text(text)
    facts: dict[str, str] = {}
    for needle, value in regime_terms().items():
        if needle in normalized and (needle != "mei" or re.search(r"\bmei\b", normalized)):
            facts["regime"] = value
    for needle, value in document_terms().items():
        if needle in normalized:
            facts["documento"] = value
            break
    operation = next((value for needle, value in operation_terms() if needle in normalized), None)
    if operation:
        facts["operação"] = operation
    add_pattern_fact(facts, "UF", UF_PATTERN, text.upper())
    add_pattern_fact(facts, "NCM", r"\bNCM\s*[:#-]?\s*(\d{4,8})\b", text.upper())
    return facts


def regime_terms() -> dict[str, str]:
    return {
        "simples nacional": "Simples Nacional",
        "lucro presumido": "Lucro Presumido",
        "lucro real": "Lucro Real",
        "mei": "MEI",
    }


def document_terms() -> dict[str, str]:
    return {"nf-e": "NF-e", "nfe": "NF-e", "nfs-e": "NFS-e", "nfse": "NFS-e", "ct-e": "CT-e"}


def operation_terms() -> tuple[tuple[str, str], ...]:
    return (
        ("prestação de serviço", "serviço"),
        ("prestacao de servico", "serviço"),
        ("vende", "venda"),
        ("venda", "venda"),
        ("importação", "importação"),
        ("importacao", "importação"),
    )


def add_pattern_fact(facts: dict[str, str], key: str, pattern: str, text: str) -> None:
    match = re.search(pattern, text)
    if match:
        facts[key] = match.group(1)


def detect_dialogue_act(message: str, history: list[dict[str, str]], document: object) -> str:
    normalized = normalize_text(message)
    if document and any(term in normalized for term in ("achados", "corrijo", "corrigir", "alertas")):
        return "document_follow_up"
    if re.fullmatch(r"(oi|olá|ola|bom dia|boa tarde|boa noite)[!. ]*", normalized):
        return "greeting"
    if any(term in normalized for term in ("obrigado", "obrigada", "valeu", "até mais", "ate mais")):
        return "closing"
    if asks_how_to_provide(normalized):
        return "provide_data"
    if history and has_follow_up_reference(normalized):
        return "follow_up"
    if not history and has_follow_up_reference(normalized):
        return "vague_without_context"
    if len(normalized.split()) <= 3 and normalized in {"sim", "não", "nao", "continue", "entendi", "certo", "ok"}:
        return "short_reply"
    return "question"


def asks_how_to_provide(message: str) -> bool:
    terms = ("como posso te informar", "como te informo", "o que você precisa", "quais dados", "o que devo enviar")
    return any(term in message for term in terms)


def has_follow_up_reference(message: str) -> bool:
    terms = ("isso", "esses achados", "nesse caso", "neste caso", "e se", "então", "entao", "e como", "e quando")
    return any(re.search(rf"(?:^|\s){re.escape(term)}(?:\b|[,.?!])", message) for term in terms)


def classify_intent(message: str, dialogue_act: str, previous_intent: str | None) -> str:
    normalized = normalize_text(message)
    if dialogue_act == "vague_without_context":
        return "clarification"
    if any(term in normalized for term in ("previsão do tempo", "futebol", "receita de bolo", "filme", "música")):
        return "off_topic"
    if dialogue_act in {"provide_data", "follow_up", "short_reply", "document_follow_up"} and previous_intent:
        return previous_intent
    if any(term in normalized for term in ("split", "fluxo de caixa", "recebe líquido", "liquidação")):
        return "split_payment"
    if any(term in normalized for term in ("nota", "nfe", "nf-e", "xml", "documento fiscal", "campos em branco")):
        return "invoice"
    if any(term in normalized for term in ("carteira", "clientes", "priorizar")):
        return "portfolio"
    return "tax_question"


def requires_live_official_search(state: AgentState) -> bool:
    return state.get("intent") in MATERIAL_INTENTS and state.get("dialogue_act") not in LOCAL_DIALOGUE_ACTS


def safe_abstention() -> str:
    return (
        "Não vou afirmar uma regra fiscal material sem consulta atualizada a fontes oficiais. A consulta ao vivo "
        "não está disponível agora, então este turno fica sem conclusão. Confirme regime, operação, documento e "
        "data do caso com a contadora e tente novamente."
    )


def local_navigation_answer(state: AgentState) -> str:
    dialogue_act = state.get("dialogue_act")
    if dialogue_act == "greeting":
        return "Olá! Posso pesquisar uma regra atual, orientar quais dados sintéticos usar ou fazer uma triagem de XML demonstrativo."
    if dialogue_act == "closing":
        return "Por nada. A conversa permanece disponível apenas durante esta sessão do piloto."
    if dialogue_act == "vague_without_context":
        return "Quero evitar supor o assunto errado. Você fala de NF-e, split payment ou outro ponto da reforma?"
    if dialogue_act == "provide_data":
        return provide_data_answer(state)
    if dialogue_act == "document_follow_up":
        return document_follow_up_answer(state)
    if dialogue_act == "short_reply":
        return "Certo. Informe primeiro o regime, a operação, o documento fiscal e a data, sempre com dados sintéticos."
    if state.get("intent") == "off_topic":
        return "Meu escopo é a Reforma Tributária do Consumo. Posso ajudar com IBS/CBS, documentos fiscais ou split payment."
    if state.get("intent") == "portfolio":
        return "A carteira exibida é totalmente sintética. Use-a apenas para testar priorização, nunca como dado real de cliente."
    return safe_abstention()


def provide_data_answer(state: AgentState) -> str:
    known = state.get("fibers", {}).get("client", {}).get("facts", {})
    summary = ", ".join(f"{key}: {value}" for key, value in known.items()) or "nenhum dado confirmado"
    return (
        "Informe somente dados sintéticos: regime, operação, data, UF ou município e tipo de documento. Para XML, "
        f"use o arquivo demonstrativo da interface. Contexto já confirmado: {summary}."
    )


def document_follow_up_answer(state: AgentState) -> str:
    document: dict[str, Any] = state.get("fibers", {}).get("document") or {}
    titles = [finding.get("title", "alerta") for finding in document.get("findings", [])]
    summary = ", ".join(titles) or "nenhum alerta estrutural específico"
    return (
        f"A triagem anterior registrou: {summary}. Corrija no emissor, gere outro XML sintético e valide no schema "
        "e no autorizador oficial. Esta ferramenta não autoriza nem certifica o documento."
    )
