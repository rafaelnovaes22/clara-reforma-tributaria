from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .application import SCENARIOS, ClaraApplication, governance_manifest
from .documents import calculate_split, triage_xml
from .security import (
    PilotPrincipal,
    RequestValidationError,
    parse_basic_principal,
    protected_identifier,
    scoped_memory_key,
    security_policy,
    validate_host,
    validate_write_headers,
)
from .sessions import PilotSession
from .settings import PROJECT_ROOT

FRONTEND_PATH = PROJECT_ROOT / "frontend"
VALIDATION_STATUS = {
    "unsupported_media_type": HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    "content_encoding_not_allowed": HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    "body_too_large": HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    "xml_too_large": HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    "content_length_required": HTTPStatus.LENGTH_REQUIRED,
    "origin_not_allowed": HTTPStatus.FORBIDDEN,
    "origin_invalid": HTTPStatus.FORBIDDEN,
    "host_not_allowed": HTTPStatus.FORBIDDEN,
    "csrf_header_missing": HTTPStatus.FORBIDDEN,
    "csrf_invalid": HTTPStatus.FORBIDDEN,
    "session_required": HTTPStatus.FORBIDDEN,
}
ROUTE_NOT_FOUND_RESPONSE = {"error": "Rota não encontrada.", "code": "route_not_found"}
REQUEST_TIMEOUT_RESPONSE = {"error": "Tempo de leitura excedido.", "code": "request_timeout"}
INTERNAL_ERROR_RESPONSE = {
    "error": "Falha interna ao processar a requisição.",
    "code": "internal_error",
}


class ClaraRequestHandler(SimpleHTTPRequestHandler):
    application: ClaraApplication
    server_version = "Clara"
    sys_version = ""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.request_id = ""
        self.response_status = 500
        self.request_started = 0.0
        self.actor_log_id = "anonymous"
        self.request_body_consumed = False
        super().__init__(*args, directory=str(FRONTEND_PATH), **kwargs)

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self.application.settings.request_timeout_seconds)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_response(self, code: int, message: str | None = None) -> None:
        self.response_status = int(code)
        super().send_response(code, message)

    def end_headers(self) -> None:
        self.send_header("X-Request-ID", self.request_id or str(uuid.uuid4()))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        self.send_header("Content-Security-Policy", security_policy())
        if self.application.settings.environment == "pilot":
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        super().end_headers()

    def do_GET(self) -> None:
        self._begin_request()
        try:
            self._route_get()
        except ConnectionError:
            self._log_aborted_response()
        finally:
            self._finish_request()

    def do_HEAD(self) -> None:
        self._begin_request()
        try:
            principal = self._authenticated_principal()
            if principal is None:
                return
            self._validate_host()
            super().do_HEAD()
        except ConnectionError:
            self._log_aborted_response()
        finally:
            self._finish_request()

    def do_OPTIONS(self) -> None:
        self._begin_request()
        try:
            self.send_json(
                {"error": "Método não permitido.", "code": "method_not_allowed"},
                HTTPStatus.METHOD_NOT_ALLOWED,
                extra_headers={"Allow": "GET, HEAD, POST"},
            )
        except ConnectionError:
            self._log_aborted_response()
        finally:
            self._finish_request()

    def do_POST(self) -> None:
        self._begin_request()
        try:
            self._route_post()
        except RequestHandled:
            pass
        except RequestValidationError as exc:
            status = VALIDATION_STATUS.get(exc.code, HTTPStatus.BAD_REQUEST)
            self.send_json({"error": str(exc), "code": exc.code}, status)
        except TimeoutError:
            self.send_json(REQUEST_TIMEOUT_RESPONSE, HTTPStatus.REQUEST_TIMEOUT)
        except ConnectionError:
            self._log_aborted_response()
        except Exception as exc:
            self._send_internal_error(exc)
        finally:
            self._finish_request()

    def _send_internal_error(self, error: Exception) -> None:
        self.application.logger.emit(
            "error",
            "request_failed",
            request_id=self.request_id,
            path=self._path(),
            error_type=type(error).__name__,
        )
        self.send_json(INTERNAL_ERROR_RESPONSE, HTTPStatus.INTERNAL_SERVER_ERROR)

    def send_json(
        self,
        payload: dict[str, Any],
        status: int = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if int(status) >= 400:
            self._drain_rejected_body()
        response_payload = {**payload}
        if int(status) >= 400:
            response_payload["request_id"] = self.request_id
        body = json.dumps(response_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self._write_json_response(body, status, extra_headers or {})
        except ConnectionError:
            self._log_aborted_response()

    def _write_json_response(self, body: bytes, status: int, extra_headers: dict[str, str]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in extra_headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _log_aborted_response(self) -> None:
        self.application.logger.emit(
            "info",
            "response_aborted",
            request_id=self.request_id,
            path=self._path(),
        )

    def _route_get(self) -> None:
        path = self._path()
        if path in {"/api/health", "/healthz"}:
            self.send_json({"status": "ok"})
            return
        if path == "/api/ready":
            ready, details = self.application.readiness()
            self.send_json(details, HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if (principal := self._authenticated_principal()) is None:
            return
        self._validate_host()
        if path == "/api/session":
            self._send_session(principal)
            return
        if path == "/api/demo-data":
            self.send_json(self._demo_data_payload())
            return
        super().do_GET()

    def _demo_data_payload(self) -> dict[str, Any]:
        return {
            "sources": self.application.sources,
            "scenarios": SCENARIOS,
            "pilot_policy": "dados_sinteticos_e_revisao_obrigatoria",
            "governance": governance_manifest(),
        }

    def _route_post(self) -> None:
        path = self._path()
        if (principal := self._authenticated_principal()) is None:
            return
        self._validate_host()
        validate_write_headers(self.headers, self.application.settings.public_origin)
        session = self._require_session(principal)
        self._require_csrf(session)
        self._require_rate_capacity(principal, path)
        payload = self._read_json_body()
        if path == "/api/chat":
            self._send_chat(payload, session)
        elif path == "/api/analyze-xml":
            self._send_xml_triage(payload, session)
        elif path == "/api/split":
            self.send_json(calculate_split(payload, self.application.source("LC214")))
        elif path == "/api/session/reset":
            self._reset_session(principal, session)
        else:
            self.send_json(ROUTE_NOT_FOUND_RESPONSE, HTTPStatus.NOT_FOUND)

    def _authenticated_principal(self) -> PilotPrincipal | None:
        principal = parse_basic_principal(self.headers.get("Authorization"), self.application.settings)
        remote_subject = self._remote_subject()
        if principal is None:
            if not self.application.auth_failure_rate.allow(remote_subject):
                self.send_json(
                    {"error": "Muitas tentativas de autenticação.", "code": "auth_rate_limited"},
                    HTTPStatus.TOO_MANY_REQUESTS,
                    extra_headers={"Retry-After": "300"},
                )
                return None
            self.send_json(
                {"error": "Autenticação obrigatória.", "code": "authentication_required"},
                HTTPStatus.UNAUTHORIZED,
                extra_headers={"WWW-Authenticate": 'Basic realm="Clara Pilot", charset="UTF-8"'},
            )
            return None
        self.actor_log_id = protected_identifier(principal.actor_id, self.application.settings.audit_hash_key)
        return principal

    def _send_session(self, principal: PilotPrincipal) -> None:
        session, cookie_header = self.application.sessions.resolve_or_create(
            principal,
            self.headers.get("Cookie"),
        )
        headers = {"Set-Cookie": cookie_header} if cookie_header else None
        self.send_json(
            {
                "csrf_token": session.csrf_token,
                "client_id": session.client_id,
                "expires_in_seconds": 7200,
            },
            extra_headers=headers,
        )

    def _require_session(self, principal: PilotPrincipal) -> PilotSession:
        session = self.application.sessions.resolve_existing(principal, self.headers.get("Cookie"))
        if session is None:
            raise RequestValidationError("session_required", "Inicie uma sessão autenticada antes de enviar dados.")
        return session

    def _require_csrf(self, session: PilotSession) -> None:
        if not self.application.sessions.valid_csrf(session, self.headers.get("X-CSRF-Token")):
            raise RequestValidationError("csrf_invalid", "Token de sessão inválido.")

    def _require_rate_capacity(self, principal: PilotPrincipal, path: str) -> None:
        global_ok = self.application.global_rate.allow("process")
        actor_ok = self.application.actor_rate.allow(principal.actor_id)
        route_ok = self._route_limiter_allows(principal.actor_id, path)
        if not global_ok or not actor_ok or not route_ok:
            self.send_json(
                {"error": "Limite temporário de requisições atingido.", "code": "rate_limited"},
                HTTPStatus.TOO_MANY_REQUESTS,
                extra_headers={"Retry-After": "60"},
            )
            raise RequestHandled()

    def _route_limiter_allows(self, actor_id: str, path: str) -> bool:
        if path == "/api/chat":
            return self.application.chat_rate.allow(actor_id)
        if path == "/api/analyze-xml":
            return self.application.xml_rate.allow(actor_id)
        return True

    def _read_json_body(self) -> dict[str, Any]:
        validate_transport_headers(self.headers)
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise RequestValidationError("content_length_required", "Content-Length é obrigatório.")
        length = parse_content_length(raw_length)
        if length > self.application.settings.max_body_bytes:
            raise RequestValidationError(
                "body_too_large",
                f"O corpo possui {length} bytes; o limite é {self.application.settings.max_body_bytes}.",
            )
        body = self.rfile.read(length)
        self.request_body_consumed = True
        if len(body) != length:
            raise RequestValidationError("incomplete_body", "O corpo terminou antes do Content-Length informado.")
        return parse_json_object(body)

    def _drain_rejected_body(self) -> None:
        if self.command != "POST" or self.request_body_consumed:
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if 0 < length <= self.application.settings.max_body_bytes:
            try:
                self.rfile.read(length)
                self.request_body_consumed = True
            except OSError:
                self.close_connection = True

    def _send_chat(self, payload: dict[str, Any], session: PilotSession) -> None:
        message = str(payload.get("message") or "")
        self.send_json(self.application.conversation.run_chat(message, self.application.scope(session)))

    def _send_xml_triage(self, payload: dict[str, Any], session: PilotSession) -> None:
        scope = self.application.scope(session)
        result = triage_xml(payload, self.application.settings, self.application.source("RFB2026"))
        summary = {
            "precheck_only": True,
            "findings": [
                {"code": item["code"], "severity": item["severity"], "title": item["title"]}
                for item in result["findings"]
            ],
        }
        self.application.conversation.remember_document(scope, summary)
        self.application.audit.record_document(
            result["run_id"],
            scope,
            [item["code"] for item in result["findings"]],
        )
        self.send_json(result)

    def _reset_session(self, principal: PilotPrincipal, session: PilotSession) -> None:
        old_scope = self.application.scope(session)
        old_key = scoped_memory_key(old_scope.actor_id, old_scope.client_id, old_scope.session_id)
        self.application.memory.delete(old_key)
        created, cookie_header = self.application.sessions.reset(principal, session)
        self.send_json(
            {"csrf_token": created.csrf_token, "message": "Nova sessão iniciada."},
            extra_headers={"Set-Cookie": cookie_header},
        )

    def _validate_host(self) -> None:
        validate_host(self.headers, self.application.settings.public_origin)

    def _path(self) -> str:
        return urlparse(self.path).path

    def _remote_subject(self) -> str:
        return protected_identifier(self.client_address[0], self.application.settings.audit_hash_key)

    def _begin_request(self) -> None:
        self.request_id = str(uuid.uuid4())
        self.request_started = time.monotonic()
        self.response_status = 500

    def _finish_request(self) -> None:
        duration_ms = round((time.monotonic() - self.request_started) * 1000, 2)
        self.application.logger.emit(
            "info",
            "http_request",
            request_id=self.request_id,
            method=self.command,
            path=self._path(),
            status=self.response_status,
            duration_ms=duration_ms,
            actor=self.actor_log_id,
            remote=self._remote_subject(),
        )


class RequestHandled(RequestValidationError):
    def __init__(self) -> None:
        super().__init__("already_handled", "A resposta já foi enviada.")


def validate_transport_headers(headers: Any) -> None:
    if headers.get("Transfer-Encoding"):
        raise RequestValidationError("transfer_encoding_not_allowed", "Transfer-Encoding não é aceito.")
    content_encoding = headers.get("Content-Encoding", "identity").strip().lower()
    if content_encoding not in {"", "identity"}:
        raise RequestValidationError("content_encoding_not_allowed", "Content-Encoding precisa ser identity.")


def parse_content_length(raw_length: str) -> int:
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise RequestValidationError(
            "invalid_content_length", "Content-Length precisa ser um inteiro positivo."
        ) from exc
    if length <= 0:
        raise RequestValidationError("invalid_content_length", "Content-Length precisa ser um inteiro positivo.")
    return length


def parse_json_object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"), parse_constant=reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RequestValidationError("invalid_json", "O corpo precisa ser um objeto JSON UTF-8 válido.") from exc
    if not isinstance(payload, dict):
        raise RequestValidationError("invalid_json_shape", "O corpo JSON precisa ser um objeto.")
    return payload


def reject_json_constant(value: str) -> None:
    raise ValueError(f"Constante JSON não permitida: {value}.")


def bind_request_handler(application: ClaraApplication) -> type[ClaraRequestHandler]:
    class BoundClaraRequestHandler(ClaraRequestHandler):
        pass

    BoundClaraRequestHandler.application = application
    return BoundClaraRequestHandler


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(
        self, server_address: tuple[str, int], handler_class: type[ClaraRequestHandler], capacity: int
    ) -> None:
        self._capacity = threading.BoundedSemaphore(capacity)
        super().__init__(server_address, handler_class)

    def process_request(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        if not self._capacity.acquire(blocking=False):
            send_capacity_response(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._capacity.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._capacity.release()


def send_capacity_response(request: socket.socket) -> None:
    body = b'{"error":"Servidor temporariamente ocupado.","code":"capacity_reached"}'
    headers = (
        b"HTTP/1.1 503 Service Unavailable\r\n"
        b"Content-Type: application/json; charset=utf-8\r\n"
        + f"Content-Length: {len(body)}\r\n".encode("ascii")
        + b"Cache-Control: no-store\r\nConnection: close\r\nRetry-After: 1\r\n\r\n"
    )
    try:
        request.sendall(headers + body)
    finally:
        request.close()


def create_http_server(
    application: ClaraApplication,
    address: tuple[str, int] | None = None,
) -> BoundedThreadingHTTPServer:
    settings = application.settings
    bind_address = address or (settings.host, settings.port)
    return BoundedThreadingHTTPServer(
        bind_address,
        bind_request_handler(application),
        settings.max_concurrent_requests,
    )
