from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import threading
import time
import unicodedata
from collections import OrderedDict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from .settings import RuntimeSettings

SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
EVASION_PATTERN = re.compile(
    r"\b(sonegar|fraudar|caixa\s+dois|ocultar\s+receita|omitir\s+faturamento|"
    r"vendas?\s+por\s+fora|fora\s+do\s+sistema|burlar\s+o\s+fisco|n[aã]o\s+declarar)\b",
    re.IGNORECASE,
)
INJECTION_PATTERNS = (
    re.compile(
        r"(ignore|override|disregard|forget|replace|desconsidere|esque[cç]a|substitua|troque|sobrescreva)\s+"
        r".{0,50}(instru[cç][oõ]es|instructions|directions|diretrizes|prompt|regras|rules|mensagens|messages)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(revele|mostre|imprima|copie|repita)\s+.{0,40}(prompt|instru[cç][oõ]es|regras|segredo)", re.IGNORECASE
    ),
    re.compile(r"\b(system|developer)\s*(prompt|message|:)\b", re.IGNORECASE),
    re.compile(r"(finja|aja)\s+.{0,30}(sistema|sem\s+regras|modo\s+desenvolvedor)", re.IGNORECASE),
)
FRAGMENTED_TOKEN_PATTERN = re.compile(r"(?<!\w)(?:[a-zà-ú][\s._-]+){2,}[a-zà-ú](?!\w)", re.IGNORECASE)


class RequestValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PilotPrincipal:
    actor_id: str


def parse_basic_principal(header: str | None, settings: RuntimeSettings) -> PilotPrincipal | None:
    if not settings.require_auth:
        return PilotPrincipal(actor_id=settings.pilot_username or "local-operator")
    if not settings.pilot_username or not settings.pilot_password:
        return None
    if not header or not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    username_ok = hmac.compare_digest(username, settings.pilot_username)
    password_ok = hmac.compare_digest(password, settings.pilot_password)
    return PilotPrincipal(actor_id=username) if username_ok and password_ok else None


def validate_scope_identifier(value: object, field_name: str, default: str) -> str:
    normalized = str(value or default).strip()
    if not SCOPE_PATTERN.fullmatch(normalized):
        raise RequestValidationError(
            "invalid_scope",
            f"{field_name} recebeu valor inválido; use de 1 a 80 letras, números, ponto, hífen ou sublinhado.",
        )
    return normalized


def scoped_memory_key(actor_id: str, client_id: str, session_id: str) -> str:
    serialized = json.dumps([actor_id, client_id, session_id], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def protected_identifier(value: str, secret: str) -> str:
    key = secret.encode("utf-8") if secret else b"local-audit-key"
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def detect_policy_violation(untrusted_texts: Iterable[str]) -> str | None:
    combined = "\n".join(normalize_untrusted_text(text) for text in untrusted_texts)
    if EVASION_PATTERN.search(combined):
        return "evasion"
    if any(pattern.search(combined) for pattern in INJECTION_PATTERNS):
        return "prompt_injection"
    return None


def normalize_untrusted_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    visible = "".join(character for character in normalized if unicodedata.category(character) != "Cf")
    joined_tokens = FRAGMENTED_TOKEN_PATTERN.sub(collapse_fragmented_token, visible)
    return re.sub(r"\s+", " ", joined_tokens).casefold().strip()


def collapse_fragmented_token(match: re.Match[str]) -> str:
    return re.sub(r"[\s._-]+", "", match.group(0))


def validate_write_headers(headers: Mapping[str, str], public_origin: str) -> None:
    content_type = headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise RequestValidationError("unsupported_media_type", "Envie o corpo como application/json.")
    if headers.get("X-Clara-Request") != "1":
        raise RequestValidationError("csrf_header_missing", "Cabeçalho de segurança ausente.")
    origin = headers.get("Origin", "").rstrip("/")
    if public_origin and origin != public_origin:
        raise RequestValidationError("origin_not_allowed", "Origem da requisição não permitida.")
    if origin and not valid_http_origin(origin):
        raise RequestValidationError("origin_invalid", "Origem da requisição inválida.")


def validate_host(headers: Mapping[str, str], public_origin: str) -> None:
    if not public_origin:
        return
    expected_host = (urlparse(public_origin).netloc or "").casefold()
    received_host = headers.get("Host", "").strip().casefold()
    if not expected_host or not hmac.compare_digest(received_host, expected_host):
        raise RequestValidationError("host_not_allowed", "Host da requisição não permitido.")


def valid_http_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.path.strip("/")


def security_policy() -> str:
    directives = (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "connect-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    )
    return "; ".join(directives)


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60, max_buckets: int = 500) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._max_buckets = max_buckets
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, subject: str, now: float | None = None) -> bool:
        instant = time.monotonic() if now is None else now
        cutoff = instant - self._window_seconds
        with self._lock:
            bucket = self._buckets.setdefault(subject, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._limit:
                return False
            bucket.append(instant)
            self._buckets.move_to_end(subject)
            while len(self._buckets) > self._max_buckets:
                self._buckets.popitem(last=False)
        return True
