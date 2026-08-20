from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.clara.audit import AuditRecorder, StructuredEventLogger  # noqa: E402
from backend.clara.contracts import ConversationScope, ModelAnswer  # noqa: E402
from backend.clara.conversation import EVAL_SUITE_VERSION, ConversationEngine  # noqa: E402
from backend.clara.memory import BoundedConversationMemory  # noqa: E402
from backend.clara.settings import RuntimeSettings  # noqa: E402


class OfflineMaterialQuestionClient:
    def answer_material_question(self, state: object) -> ModelAnswer:
        return ModelAnswer(None, "safe_abstention", [], "offline_eval")


def build_engine() -> ConversationEngine:
    # O cliente offline mantém a suíte determinística mesmo quando o ambiente possui uma chave configurada.
    settings = RuntimeSettings.from_environment({"CLARA_ENV": "test", "CLARA_DISABLE_AUDIT": "true"})
    audit = AuditRecorder(StructuredEventLogger(), "eval-hash-key", None, enabled=False)
    memory = BoundedConversationMemory(settings.max_sessions)
    return ConversationEngine(settings, memory, audit, OfflineMaterialQuestionClient())


def evaluate_case(engine: ConversationEngine, case: dict[str, Any]) -> dict[str, Any]:
    scope = ConversationScope("offline-eval", "isolated-client", f"eval-{uuid.uuid4()}")
    result = engine.run_chat(str(case["question"]), scope)
    checks = {
        "intent": result["intent"] == case["expected_intent"],
        "outcome": outcome_matches(result, str(case["expected_outcome"])),
        "required_content": all(term.casefold() in result["answer"].casefold() for term in case["must_contain"]),
        "forbidden_claims": all(
            term.casefold() not in result["answer"].casefold() for term in case["forbidden_claims"]
        ),
        "independent_gate": result["evals"].get("self_scored") is False,
        "hard_gates": bool(result["evals"].get("passed")),
    }
    return {"id": case["id"], "passed": all(checks.values()), "checks": checks}


def outcome_matches(result: dict[str, Any], expected: str) -> bool:
    if expected == "abstain":
        return result["abstained"] and result["generation_mode"] == "safe_abstention"
    if expected == "block":
        return result["blocked"] and result["generation_mode"] == "policy_block"
    if expected == "answer":
        return not result["blocked"] and not result["abstained"]
    raise ValueError(f"expected_outcome inválido no caso de eval: {expected!r}.")


def maybe_write_latest(summary: dict[str, Any]) -> None:
    if os.environ.get("CLARA_EVAL_NO_WRITE") == "1":
        return
    output = Path(__file__).with_name("latest_results.json")
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    cases = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
    engine = build_engine()
    rows = [evaluate_case(engine, case) for case in cases]
    passed = sum(1 for row in rows if row["passed"])
    summary = {
        "suite": EVAL_SUITE_VERSION,
        "mode": "offline_safety_contract",
        "total": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "pass_rate": round(passed / len(rows), 2),
        "results": rows,
    }
    maybe_write_latest(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
