from __future__ import annotations

import base64
import json
import socket
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from backend.clara.application import ClaraApplication
from backend.clara.http_api import create_http_server
from backend.clara.security import PilotPrincipal, scoped_memory_key
from backend.clara.settings import RuntimeSettings


@dataclass(slots=True)
class HttpResult:
    status: int
    payload: Any
    headers: Any


@dataclass(slots=True)
class HttpRequestSpec:
    path: str
    method: str
    payload: dict[str, Any] | None
    authenticated: bool
    include_csrf: bool
    origin: str | None
    content_type: str
    raw_body: bytes | None
    host: str


SPLIT_PAYLOAD = {"gross": 100, "ibs_rate": 0.1, "cbs_rate": 0.9}


def http_test_settings() -> RuntimeSettings:
    return RuntimeSettings.from_environment(
        {
            "CLARA_ENV": "test",
            "CLARA_REQUIRE_AUTH": "true",
            "CLARA_PUBLIC_ORIGIN": "http://clara.example",
            "CLARA_PILOT_USERNAME": "contadora",
            "CLARA_PILOT_PASSWORD": "senha-segura-com-24-caracteres",
            "CLARA_PILOT_CLIENT_ID": "cliente-fixo",
            "CLARA_AUDIT_HASH_KEY": "chave-hash-para-testes",
            "CLARA_DISABLE_AUDIT": "true",
        }
    )


class RunningClaraServer:
    def __init__(self) -> None:
        self.application = ClaraApplication.build(http_test_settings())
        self.application.logger.emit = lambda *args, **kwargs: None
        self.server = create_http_server(self.application, ("127.0.0.1", 0))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        encoded = base64.b64encode(b"contadora:senha-segura-com-24-caracteres").decode("ascii")
        self.authorization = f"Basic {encoded}"
        self.cookie = ""
        self.csrf = ""

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def create_session(self) -> None:
        result = self.request("/api/session", authenticated=True)
        self.cookie = result.headers["Set-Cookie"].split(";", 1)[0]
        self.csrf = result.payload["csrf_token"]

    def request(
        self,
        path: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        authenticated: bool = False,
        include_csrf: bool = False,
        origin: str | None = None,
        content_type: str = "application/json",
        raw_body: bytes | None = None,
        host: str = "clara.example",
    ) -> HttpResult:
        spec = HttpRequestSpec(path, method, payload, authenticated, include_csrf, origin, content_type, raw_body, host)
        return self._perform_request(spec)

    def _perform_request(self, spec: HttpRequestSpec) -> HttpResult:
        body = spec.raw_body
        if body is None and spec.payload is not None:
            body = json.dumps(spec.payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(f"{self.base_url}{spec.path}", data=body, method=spec.method)
        self._add_request_headers(request, spec)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return self._read_success(response)
        except urllib.error.HTTPError as exc:
            return HttpResult(exc.code, json.loads(exc.read()), exc.headers)

    def _add_request_headers(self, request: urllib.request.Request, spec: HttpRequestSpec) -> None:
        request.add_header("Host", spec.host)
        if spec.authenticated:
            request.add_header("Authorization", self.authorization)
        if spec.method != "POST":
            return
        request.add_header("Content-Type", spec.content_type)
        request.add_header("X-Clara-Request", "1")
        if spec.origin is not None:
            request.add_header("Origin", spec.origin)
        if self.cookie:
            request.add_header("Cookie", self.cookie)
        if spec.include_csrf:
            request.add_header("X-CSRF-Token", self.csrf)

    def _read_success(self, response: Any) -> HttpResult:
        response_body = response.read()
        content_type = response.headers.get("Content-Type", "")
        payload = json.loads(response_body) if "application/json" in content_type else response_body.decode("utf-8")
        return HttpResult(response.status, payload, response.headers)

    def split_request(self, origin: str, content_type: str = "application/json") -> HttpResult:
        return self.request(
            "/api/split",
            method="POST",
            payload=SPLIT_PAYLOAD,
            authenticated=True,
            include_csrf=True,
            origin=origin,
            content_type=content_type,
        )

    def raw_post_status(self, content_length: str | None) -> int:
        headers = [
            "POST /api/split HTTP/1.1",
            "Host: clara.example",
            f"Authorization: {self.authorization}",
            "Origin: http://clara.example",
            "X-Clara-Request: 1",
            f"X-CSRF-Token: {self.csrf}",
            f"Cookie: {self.cookie}",
            "Content-Type: application/json",
            "Connection: close",
        ]
        if content_length is not None:
            headers.append(f"Content-Length: {content_length}")
        request = "\r\n".join([*headers, "", ""]).encode("ascii")
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as connection:
            connection.sendall(request)
            response = connection.recv(512).decode("iso-8859-1")
        return int(response.split(" ", 2)[1])


class HttpSecurityIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.running = RunningClaraServer()

    def tearDown(self) -> None:
        self.running.close()

    def test_health_and_readiness_are_public_and_minimal(self) -> None:
        health = self.running.request("/api/health")
        readiness = self.running.request("/api/ready")
        self.assertEqual(health.payload, {"status": "ok"})
        self.assertEqual(readiness.status, 200)
        self.assertEqual(readiness.payload["status"], "ready")

    def test_static_content_requires_basic_auth_and_has_security_headers(self) -> None:
        denied = self.running.request("/")
        allowed = self.running.request("/", authenticated=True)
        self.assertEqual(denied.status, 401)
        self.assertIn("Basic", denied.headers["WWW-Authenticate"])
        self.assertEqual(allowed.status, 200)
        self.assertIn("default-src 'self'", allowed.headers["Content-Security-Policy"])
        self.assertEqual(allowed.headers["X-Frame-Options"], "DENY")
        self.assertNotIn("Access-Control-Allow-Origin", allowed.headers)

    def test_session_cookie_and_csrf_protect_state_changes(self) -> None:
        self.running.create_session()
        denied = self.running.request(
            "/api/split",
            method="POST",
            payload={"gross": 100, "ibs_rate": 0.1, "cbs_rate": 0.9},
            authenticated=True,
            origin="http://clara.example",
        )
        allowed = self.running.request(
            "/api/split",
            method="POST",
            payload={"gross": 100, "ibs_rate": 0.1, "cbs_rate": 0.9},
            authenticated=True,
            include_csrf=True,
            origin="http://clara.example",
        )
        self.assertEqual(denied.status, 403)
        self.assertEqual(allowed.status, 200)
        self.assertEqual(allowed.payload["net"], 99.0)

    def test_origin_content_type_and_options_fail_closed(self) -> None:
        self.running.create_session()
        wrong_origin = self.running.split_request("http://evil.example")
        text_plain = self.running.split_request("http://clara.example", "text/plain")
        options = self.running.request("/api/split", method="OPTIONS")
        self.assertEqual(wrong_origin.status, 403)
        self.assertEqual(text_plain.status, 415)
        self.assertEqual(options.status, 405)
        self.assertNotIn("Access-Control-Allow-Origin", options.headers)

    def test_host_and_origin_lookalikes_are_rejected(self) -> None:
        self.running.create_session()
        attempts = (
            {"host": "evil.example", "origin": "http://clara.example"},
            {"host": "clara.example", "origin": "http://sub.clara.example"},
            {"host": "clara.example", "origin": "null"},
        )
        for headers in attempts:
            with self.subTest(headers=headers):
                response = self.running.request(
                    "/api/split",
                    method="POST",
                    payload={"gross": 100, "ibs_rate": 0.1, "cbs_rate": 0.9},
                    authenticated=True,
                    include_csrf=True,
                    **headers,
                )
                self.assertEqual(response.status, 403)

    def test_content_length_is_required_and_capped_before_read(self) -> None:
        self.running.create_session()
        self.assertEqual(self.running.raw_post_status(None), 411)
        self.assertEqual(self.running.raw_post_status("786433"), 413)

    def test_browser_ids_are_ignored_in_favor_of_server_session(self) -> None:
        self.running.create_session()
        response = self.running.request(
            "/api/chat",
            method="POST",
            payload={"message": "Olá", "client_id": "attacker", "session_id": "attacker"},
            authenticated=True,
            include_csrf=True,
            origin="http://clara.example",
        )
        session = self.running.application.sessions.resolve_existing(PilotPrincipal("contadora"), self.running.cookie)
        self.assertEqual(response.status, 200)
        self.assertIsNotNone(session)
        assert session is not None
        server_key = scoped_memory_key("contadora", "cliente-fixo", session.session_id)
        attacker_key = scoped_memory_key("contadora", "attacker", "attacker")
        self.assertTrue(self.running.application.memory.snapshot(server_key))
        self.assertEqual(self.running.application.memory.snapshot(attacker_key), {})

    def test_openai_configuration_route_is_removed(self) -> None:
        self.running.create_session()
        response = self.running.request(
            "/api/openai/configure",
            method="POST",
            payload={"api_key": "browser-key-should-never-be-accepted"},
            authenticated=True,
            include_csrf=True,
            origin="http://clara.example",
        )
        self.assertEqual(response.status, 404)

    def test_nonstandard_json_constant_is_rejected_without_internal_details(self) -> None:
        self.running.create_session()
        response = self.running.request(
            "/api/split",
            method="POST",
            authenticated=True,
            include_csrf=True,
            origin="http://clara.example",
            raw_body=b'{"gross":NaN,"ibs_rate":0.1,"cbs_rate":0.9}',
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(response.payload["code"], "invalid_json")
        self.assertNotIn("Traceback", json.dumps(response.payload))

    def test_eleventh_chat_request_is_rate_limited(self) -> None:
        self.running.create_session()
        responses = [
            self.running.request(
                "/api/chat",
                method="POST",
                payload={"message": "Olá"},
                authenticated=True,
                include_csrf=True,
                origin="http://clara.example",
            )
            for _ in range(11)
        ]
        self.assertTrue(all(response.status == 200 for response in responses[:10]))
        self.assertEqual(responses[-1].status, 429)
        self.assertEqual(responses[-1].headers["Retry-After"], "60")

    def test_server_handles_twenty_parallel_health_checks(self) -> None:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: self.running.request("/api/health"), range(20)))
        self.assertTrue(all(result.status == 200 for result in results))


if __name__ == "__main__":
    unittest.main()
