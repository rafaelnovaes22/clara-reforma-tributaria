from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.clara.knowledge import official_https_url  # noqa: E402

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36 ClaraPilot/1.0"
)


def load_urls() -> list[tuple[str, str]]:
    registry = json.loads((ROOT / "data" / "regulatory_sources.json").read_text(encoding="utf-8"))
    urls = [(source["id"], source["url"]) for source in registry["sources"]]
    return sorted(urls, key=lambda item: item[1])


def create_source_client() -> httpx.Client:
    headers = {"User-Agent": BROWSER_USER_AGENT, "Accept": "text/html,*/*"}
    # O gate mede a rota direta do serviço e não proxies injetados na estação de desenvolvimento.
    return httpx.Client(headers=headers, follow_redirects=True, timeout=15, trust_env=False)


def check_source(client: httpx.Client, source_id: str, url: str) -> dict[str, object]:
    try:
        response = client.get(url)
        final_url = str(response.url)
        return {
            "id": source_id,
            "passed": response.status_code == 200 and official_https_url(final_url),
            "status": response.status_code,
            "final_url": final_url,
        }
    except httpx.HTTPError:
        return {"id": source_id, "passed": False, "status": None, "error": "network_error"}


def main() -> int:
    with create_source_client() as client:
        results = [check_source(client, source_id, url) for source_id, url in load_urls()]
    passed = all(bool(result["passed"]) for result in results)
    print(json.dumps({"status": "passed" if passed else "failed", "results": results}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
