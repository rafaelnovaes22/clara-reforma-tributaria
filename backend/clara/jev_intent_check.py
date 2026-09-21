"""Segunda opinião calibrada sobre o intent da conversa (shadow, sem efeito no fluxo).

O classify_intent determinístico decide; o Jev valida com choice calibrado mais
um noul independente de materialidade fiscal. Divergência só gera log para a
contadora calibrar. Entrada nunca contém dado real: piloto só usa sintético.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass

from .dialogue import MATERIAL_INTENTS

JEV_MODEL_PINNED = "jev-1.13.0"
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MAX_STATE_CHARS = 2000
JEV_DEFAULT_TIMEOUT_S = 2.0

ACT = 0.7
ESCALATE_BELOW = 0.5

VALID_INTENTS = (
    "invoice",
    "split_payment",
    "tax_question",
    "portfolio",
    "off_topic",
    "clarification",
)

INTENT_CRITERIA = {
    "invoice": "Asks about NF-e, NFS-e, CT-e, fiscal documents, XML, or blank fields.",
    "split_payment": "Asks about split payment, cash flow, net receipt, or settlement.",
    "tax_question": "Asks a material tax rule question about IBS, CBS, or the reform.",
    "portfolio": "Asks about the client portfolio, prioritizing, or wallet.",
    "off_topic": "Clearly outside tax scope: weather, football, recipes, movies, music.",
    "clarification": "Too vague to classify without more context.",
}


@dataclass(frozen=True)
class JevIntentCheck:
    choice: str
    choice_confidence: float
    material_noul: float
    material: bool
    escalate: bool
    model: str
    latency_ms: int
    mocked: bool = False


def sanitize_state_text(raw: str) -> str:
    if not raw:
        return ""
    clean = "".join(ch for ch in raw if ch in {"\n", "\t"} or 32 <= ord(ch) < 127 or ord(ch) >= 160)
    clean = " ".join(clean.split())
    return clean[:JEV_MAX_STATE_CHARS]


def is_configured(api_key: str | None) -> bool:
    if not api_key or len(api_key) < 8:
        return False
    return "..." not in api_key


def build_body(state: str, model: str) -> dict:
    return {
        "state": state,
        "model": model,
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": "Which Clara conversation intent matches the message?",
                "criteria": {k: INTENT_CRITERIA[k] for k in VALID_INTENTS},
            },
            "material": {
                "type": "noul",
                "instructions": "The message asks a material fiscal question about invoices, split payment, or tax rules.",
            },
        },
    }


def clamp01(value: object, fallback: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return min(1.0, max(0.0, float(value)))


def parse_response(body: object) -> dict | None:
    if not isinstance(body, dict):
        return None
    answers = body.get("answers")
    if not isinstance(answers, dict):
        return None
    intent = answers.get("intent")
    material = answers.get("material")
    if not isinstance(intent, dict) or not isinstance(material, dict):
        return None
    if intent.get("choice") not in VALID_INTENTS:
        return None
    return {
        "choice": intent["choice"],
        "choice_confidence": clamp01(intent.get("confidence"), 0.5),
        "material_noul": clamp01(material.get("noul"), 0.5),
        "model": body.get("model") or JEV_MODEL_PINNED,
    }


def default_post(payload: bytes, api_key: str, timeout_s: float) -> dict | None:
    request = urllib.request.Request(
        JEV_ENDPOINT,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            if response.status != 200:
                return None
            return parse_response(json.loads(response.read().decode("utf-8")))
    except Exception:
        return None


def query_intent_check(
    text: str,
    *,
    api_key: str | None,
    model: str = JEV_MODEL_PINNED,
    timeout_s: float = JEV_DEFAULT_TIMEOUT_S,
    enabled: bool = False,
    post=None,
) -> JevIntentCheck | None:
    if not enabled or not is_configured(api_key):
        return None
    state = sanitize_state_text(text)
    if not state:
        return None
    post_fn = post or default_post
    payload = json.dumps(build_body(state, model)).encode("utf-8")
    start = time.monotonic()
    try:
        parsed = post_fn(payload, api_key or "", timeout_s)
    except Exception:
        return None
    if parsed is None:
        return None
    latency_ms = int((time.monotonic() - start) * 1000)
    distance = abs(parsed["choice_confidence"] - 0.5) * 2
    return JevIntentCheck(
        choice=parsed["choice"],
        choice_confidence=parsed["choice_confidence"],
        material_noul=parsed["material_noul"],
        material=parsed["material_noul"] >= ACT,
        escalate=(ESCALATE_BELOW <= parsed["choice_confidence"] < ACT) or distance < ESCALATE_BELOW,
        model=parsed["model"],
        latency_ms=latency_ms,
    )


def divergence_fields(drafted_intent: str, check: JevIntentCheck | None) -> dict | None:
    """Retorna campos de log quando há divergência, ou None quando concorda."""
    if check is None:
        return None
    disagree = check.choice != drafted_intent
    tripwire = check.material and drafted_intent not in MATERIAL_INTENTS
    if not disagree and not tripwire:
        return None
    return {
        "area": "jev",
        "event": "shadow_divergence",
        "mode": "shadow",
        "drafted_intent": drafted_intent,
        "jev_choice": check.choice,
        "jev_confidence": check.choice_confidence,
        "material_noul": check.material_noul,
        "escalate": check.escalate,
        "model": check.model,
        "latency_ms": check.latency_ms,
    }
