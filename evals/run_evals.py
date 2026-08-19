from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["CLARA_DISABLE_AUDIT"] = "1"

from server import RUNTIME_SECRETS, run_chat  # noqa: E402


def main() -> int:
    # A suíte é sempre determinística, mesmo se o ambiente tiver uma chave configurada.
    RUNTIME_SECRETS["openai_api_key"] = ""
    cases = json.loads((Path(__file__).with_name("cases.json")).read_text(encoding="utf-8"))
    failures = []
    rows = []
    for case in cases:
        result = run_chat(
            {
                "message": case["question"],
                "session_id": f"eval-{case['id']}-{uuid.uuid4()}",
                "client_id": "eval-isolated-client",
            }
        )
        checks = {
            "intent": result["intent"] == case["expected_intent"],
            "content": all(text.lower() in result["answer"].lower() for text in case["must_contain"]),
            "sources": len(result["sources"]) >= case["minimum_sources"],
            "score": result["evals"]["overall"] >= case["minimum_score"],
        }
        if case.get("expected_block"):
            checks["blocked"] = any(not item["passed"] for item in result["guardrails"][:2])
        passed = all(checks.values())
        rows.append({"id": case["id"], "passed": passed, "checks": checks, "score": result["evals"]["overall"]})
        if not passed:
            failures.append(case["id"])

    summary = {
        "suite": "evals-rtc-2026.08.19-v2",
        "total": len(rows),
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "pass_rate": round((len(rows) - len(failures)) / len(rows), 2),
        "results": rows,
    }
    output = Path(__file__).with_name("latest_results.json")
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
