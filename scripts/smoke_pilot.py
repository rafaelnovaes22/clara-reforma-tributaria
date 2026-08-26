from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import urllib.request
from typing import Any


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Variável obrigatória ausente para smoke: {name}.")
    return value


def request_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    authorization: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    csrf_token: str = "",
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Authorization", authorization)
    if payload is not None:
        request.add_header("Content-Type", "application/json")
        request.add_header("X-Clara-Request", "1")
        request.add_header("X-CSRF-Token", csrf_token)
        request.add_header("Origin", url.split("/api/", 1)[0])
    with opener.open(request, timeout=15) as response:
        return json.loads(response.read())


def main() -> int:
    origin, authorization, opener = build_smoke_connection()
    health, readiness, split = run_smoke_checks(origin, authorization, opener)
    passed = (
        health["status"] == "ok" and readiness["status"] == "ready" and split["tax"] == 1.0 and split["net"] == 99.0
    )
    result = {"status": "passed" if passed else "failed", "health": health["status"], "readiness": readiness["status"]}
    print(json.dumps(result))
    return 0 if passed else 1


def build_smoke_connection() -> tuple[str, str, urllib.request.OpenerDirector]:
    origin = required_environment("CLARA_SMOKE_ORIGIN").rstrip("/")
    username = required_environment("CLARA_PILOT_USERNAME")
    password = required_environment("CLARA_PILOT_PASSWORD")
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    authorization = f"Basic {credentials}"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    return origin, authorization, opener


def run_smoke_checks(
    origin: str,
    authorization: str,
    opener: urllib.request.OpenerDirector,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    health = request_json(opener, f"{origin}/api/health", authorization)
    readiness = request_json(opener, f"{origin}/api/ready", authorization)
    session = request_json(opener, f"{origin}/api/session", authorization)
    split = request_json(
        opener,
        f"{origin}/api/split",
        authorization,
        method="POST",
        payload={"gross": 100, "ibs_rate": 0.1, "cbs_rate": 0.9},
        csrf_token=session["csrf_token"],
    )
    return health, readiness, split


if __name__ == "__main__":
    raise SystemExit(main())
