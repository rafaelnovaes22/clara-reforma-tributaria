from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .contracts import SourceRecord

SOURCE_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "regulatory_sources.json"
OFFICIAL_DOMAINS = ("planalto.gov.br", "gov.br", "cgibs.gov.br")
REQUIRED_SOURCE_FIELDS = frozenset(
    {
        "id",
        "title",
        "issuer",
        "published_at",
        "updated_at",
        "effective_from",
        "effective_to",
        "reviewed_at",
        "url",
        "tags",
        "excerpt",
        "supports_claims",
    }
)


def official_https_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    trusted_host = any(host == domain or host.endswith(f".{domain}") for domain in OFFICIAL_DOMAINS)
    return parsed.scheme == "https" and trusted_host and bool(parsed.path)


def load_source_registry(path: Path = SOURCE_REGISTRY_PATH) -> list[SourceRecord]:
    raw_registry: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_registry, dict) or not isinstance(raw_registry.get("sources"), list):
        raise ValueError(f"Registro de fontes inválido em {path}; era esperado um objeto com sources[].")
    sources = [validate_source(item, path) for item in raw_registry["sources"]]
    if len({source["id"] for source in sources}) != len(sources):
        raise ValueError(f"Registro de fontes inválido em {path}; IDs precisam ser únicos.")
    return sources


def validate_source(item: object, path: Path) -> SourceRecord:
    if not isinstance(item, dict):
        raise ValueError(f"Fonte inválida em {path}; cada entrada precisa ser um objeto.")
    _require_source_fields(item, path)
    _validate_source_url(item)
    _validate_source_dates(item)
    return SourceRecord(**item, live=False)


def _require_source_fields(item: dict[str, Any], path: Path) -> None:
    missing = sorted(REQUIRED_SOURCE_FIELDS - item.keys())
    if not missing:
        return
    source_id = item.get("id", "<sem id>")
    raise ValueError(f"Fonte {source_id} sem campos obrigatórios: {', '.join(missing)}.")


def _validate_source_url(item: dict[str, Any]) -> None:
    if official_https_url(str(item["url"])):
        return
    raise ValueError(f"Fonte {item['id']} possui URL não oficial ou sem HTTPS: {item['url']!r}.")


def _validate_source_dates(item: dict[str, Any]) -> None:
    for date_field in ("published_at", "updated_at", "effective_from", "reviewed_at"):
        date.fromisoformat(str(item[date_field]))
    if item["effective_to"] is not None:
        date.fromisoformat(str(item["effective_to"]))


def source_registry_is_fresh(sources: list[SourceRecord], today: date, max_age_days: int) -> bool:
    if not sources:
        return False
    newest_review = max(date.fromisoformat(source["reviewed_at"]) for source in sources)
    age_days = (today - newest_review).days
    return 0 <= age_days <= max_age_days


def retrieve_sources(query: str, sources: list[SourceRecord], limit: int = 3) -> list[SourceRecord]:
    query_tokens = set(re.findall(r"[a-zà-ú0-9-]+", query.casefold()))
    ranked: list[tuple[int, SourceRecord]] = []
    for source in sources:
        searchable = " ".join([*source["tags"], source["title"], source["excerpt"]]).casefold()
        score = sum(1 for token in query_tokens if len(token) > 3 and token in searchable)
        if score:
            ranked.append((score, source))
    ranked.sort(key=lambda item: (item[0], item[1]["updated_at"]), reverse=True)
    return [source for _, source in ranked[:limit]]
