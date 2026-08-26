from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPENAI_MODEL_ALLOWLIST = {"gpt-5.6-luna", "gpt-5.6-terra"}


def parse_boolean(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Valor booleano inválido: {value!r}. Use true ou false.")


def parse_integer(
    variables: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = variables.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} recebeu {raw_value!r}; era esperado um número inteiro.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} recebeu {value}; era esperado valor entre {minimum} e {maximum}.")
    return value


def resolve_audit_path(variables: Mapping[str, str], environment: str) -> Path | None:
    configured = variables.get("CLARA_AUDIT_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if environment == "local":
        return PROJECT_ROOT / "data" / "audit.jsonl"
    return None


def _parse_environment(variables: Mapping[str, str]) -> str:
    if "PORT" in variables and not variables.get("CLARA_ENV", "").strip():
        raise ValueError("CLARA_ENV é obrigatória quando PORT está definida; use pilot no ambiente publicado.")
    environment = variables.get("CLARA_ENV", "local").strip().lower()
    if environment not in {"local", "test", "pilot"}:
        raise ValueError(f"CLARA_ENV recebeu {environment!r}; use local, test ou pilot.")
    return environment


def _server_setting_values(variables: Mapping[str, str], environment: str) -> dict[str, object]:
    default_host = "0.0.0.0" if "PORT" in variables else "127.0.0.1"
    return {
        "environment": environment,
        "host": variables.get("HOST", variables.get("DEMO_HOST", default_host)).strip(),
        "port": parse_integer(variables, "PORT", int(variables.get("DEMO_PORT", "8765")), 1, 65535),
        "public_origin": variables.get("CLARA_PUBLIC_ORIGIN", "").strip().rstrip("/"),
        "require_auth": parse_boolean(variables.get("CLARA_REQUIRE_AUTH"), environment == "pilot"),
    }


def _pilot_setting_values(variables: Mapping[str, str], environment: str) -> dict[str, object]:
    return {
        "pilot_username": variables.get("CLARA_PILOT_USERNAME", "").strip(),
        "pilot_password": variables.get("CLARA_PILOT_PASSWORD", ""),
        "pilot_client_id": variables.get("CLARA_PILOT_CLIENT_ID", "piloto-contadora").strip(),
        "audit_hash_key": variables.get("CLARA_AUDIT_HASH_KEY", ""),
        "audit_path": resolve_audit_path(variables, environment),
        "audit_enabled": not parse_boolean(variables.get("CLARA_DISABLE_AUDIT"), False),
        "allow_real_xml": parse_boolean(variables.get("CLARA_ALLOW_REAL_XML"), False),
    }


def _openai_setting_values(variables: Mapping[str, str]) -> dict[str, object]:
    return {
        "openai_api_key": variables.get("OPENAI_API_KEY", "").strip(),
        "openai_model": variables.get("OPENAI_MODEL", "gpt-5.6-luna").strip(),
    }


def _limit_setting_values(variables: Mapping[str, str]) -> dict[str, object]:
    return {
        "max_body_bytes": parse_integer(variables, "CLARA_MAX_BODY_BYTES", 786_432, 16_384, 2_097_152),
        "max_message_chars": parse_integer(variables, "CLARA_MAX_MESSAGE_CHARS", 4_000, 256, 12_000),
        "max_xml_bytes": parse_integer(variables, "CLARA_MAX_XML_BYTES", 524_288, 16_384, 1_048_576),
        "max_sessions": parse_integer(variables, "CLARA_MAX_SESSIONS", 200, 10, 2_000),
        "max_requests_per_minute": parse_integer(variables, "CLARA_RATE_LIMIT", 30, 5, 300),
        "max_chat_requests_per_minute": parse_integer(variables, "CLARA_CHAT_RATE_LIMIT", 10, 1, 60),
        "max_concurrent_requests": parse_integer(variables, "CLARA_MAX_CONCURRENCY", 16, 2, 64),
        "request_timeout_seconds": parse_integer(variables, "CLARA_REQUEST_TIMEOUT", 10, 2, 60),
        "openai_timeout_seconds": parse_integer(variables, "CLARA_OPENAI_TIMEOUT", 25, 5, 60),
        "source_max_age_days": parse_integer(variables, "CLARA_SOURCE_MAX_AGE_DAYS", 14, 1, 90),
    }


def _runtime_setting_values(variables: Mapping[str, str], environment: str) -> dict[str, object]:
    return {
        **_server_setting_values(variables, environment),
        **_pilot_setting_values(variables, environment),
        **_openai_setting_values(variables),
        **_limit_setting_values(variables),
    }


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    environment: str
    host: str
    port: int
    public_origin: str
    require_auth: bool
    pilot_username: str
    pilot_password: str
    pilot_client_id: str
    audit_hash_key: str
    audit_path: Path | None
    audit_enabled: bool
    openai_api_key: str
    openai_model: str
    max_body_bytes: int
    max_message_chars: int
    max_xml_bytes: int
    max_sessions: int
    max_requests_per_minute: int
    max_chat_requests_per_minute: int
    max_concurrent_requests: int
    request_timeout_seconds: int
    openai_timeout_seconds: int
    allow_real_xml: bool
    source_max_age_days: int

    @classmethod
    def from_environment(cls, variables: Mapping[str, str] | None = None) -> RuntimeSettings:
        env = os.environ if variables is None else variables
        environment = _parse_environment(env)
        return cls(**_runtime_setting_values(env, environment))

    def readiness_failures(
        self,
        langgraph_available: bool,
        source_registry_ready: bool = True,
        required_files_ready: bool = True,
        audit_destination_ready: bool = True,
    ) -> list[str]:
        failures = _base_readiness_failures(self, source_registry_ready, required_files_ready)
        if self.environment != "pilot":
            return failures
        failures.extend(_pilot_access_failures(self, audit_destination_ready))
        failures.extend(_pilot_dependency_failures(self, langgraph_available))
        return failures


def _base_readiness_failures(
    settings: RuntimeSettings,
    source_registry_ready: bool,
    required_files_ready: bool,
) -> list[str]:
    failures: list[str] = []
    if not source_registry_ready:
        failures.append("source_registry_stale")
    if not required_files_ready:
        failures.append("required_files_missing")
    if settings.max_xml_bytes > settings.max_body_bytes:
        failures.append("xml_limit_exceeds_body_limit")
    return failures


def _pilot_access_failures(settings: RuntimeSettings, audit_destination_ready: bool) -> list[str]:
    failures: list[str] = []
    if not settings.require_auth:
        failures.append("auth_disabled")
    if not settings.pilot_username or len(settings.pilot_password) < 16:
        failures.append("pilot_credentials_missing")
    if not settings.pilot_client_id:
        failures.append("pilot_client_missing")
    if len(settings.audit_hash_key) < 16:
        failures.append("audit_hash_key_missing")
    if not settings.audit_enabled:
        failures.append("audit_disabled")
    elif not audit_destination_ready:
        failures.append("audit_destination_unavailable")
    return failures


def _pilot_dependency_failures(settings: RuntimeSettings, langgraph_available: bool) -> list[str]:
    failures: list[str] = []
    if not valid_pilot_origin(settings.public_origin):
        failures.append("https_origin_missing")
    if len(settings.openai_api_key) < 20:
        failures.append("openai_key_missing")
    if settings.openai_model not in OPENAI_MODEL_ALLOWLIST:
        failures.append("openai_model_not_allowed")
    if not langgraph_available:
        failures.append("langgraph_missing")
    if settings.allow_real_xml:
        failures.append("real_xml_not_allowed_in_pilot")
    return failures


def valid_pilot_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and parsed.path in {"", "/"}
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )
