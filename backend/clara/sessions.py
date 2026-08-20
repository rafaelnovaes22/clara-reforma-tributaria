from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie

from .security import PilotPrincipal

SESSION_TTL_SECONDS = 7_200


@dataclass(slots=True)
class PilotSession:
    actor_id: str
    client_id: str
    session_id: str
    csrf_token: str
    created_at: float
    last_seen: float


class PilotSessionRegistry:
    def __init__(self, client_id: str, max_sessions: int, secure_cookie: bool) -> None:
        self._client_id = client_id
        self._max_sessions = max_sessions
        self._secure_cookie = secure_cookie
        self._cookie_name = "__Host-clara_sid" if secure_cookie else "clara_sid"
        self._sessions: OrderedDict[str, PilotSession] = OrderedDict()
        self._lock = threading.Lock()

    def resolve_or_create(
        self,
        principal: PilotPrincipal,
        cookie_header: str | None,
        now: float | None = None,
    ) -> tuple[PilotSession, str | None]:
        instant = time.monotonic() if now is None else now
        session_token = self._session_token(cookie_header)
        with self._lock:
            self._purge_expired(instant)
            current = self._sessions.get(session_token or "")
            if current and hmac.compare_digest(current.actor_id, principal.actor_id):
                current.last_seen = instant
                self._sessions.move_to_end(current.session_id)
                return current, None
            created = self._create_locked(principal, instant)
            return created, self._cookie_header(created.session_id)

    def resolve_existing(
        self,
        principal: PilotPrincipal,
        cookie_header: str | None,
        now: float | None = None,
    ) -> PilotSession | None:
        instant = time.monotonic() if now is None else now
        session_token = self._session_token(cookie_header)
        with self._lock:
            self._purge_expired(instant)
            current = self._sessions.get(session_token or "")
            if current is None or not hmac.compare_digest(current.actor_id, principal.actor_id):
                return None
            current.last_seen = instant
            self._sessions.move_to_end(current.session_id)
            return current

    def reset(
        self, principal: PilotPrincipal, current: PilotSession, now: float | None = None
    ) -> tuple[PilotSession, str]:
        instant = time.monotonic() if now is None else now
        with self._lock:
            self._sessions.pop(current.session_id, None)
            created = self._create_locked(principal, instant)
            return created, self._cookie_header(created.session_id)

    def valid_csrf(self, session: PilotSession, received_token: str | None) -> bool:
        return bool(received_token) and hmac.compare_digest(session.csrf_token, received_token)

    def _create_locked(self, principal: PilotPrincipal, instant: float) -> PilotSession:
        session_id = secrets.token_urlsafe(32)
        session = PilotSession(
            actor_id=principal.actor_id,
            client_id=self._client_id,
            session_id=session_id,
            csrf_token=secrets.token_urlsafe(32),
            created_at=instant,
            last_seen=instant,
        )
        self._sessions[session_id] = session
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)
        return session

    def _purge_expired(self, instant: float) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if instant - session.last_seen > SESSION_TTL_SECONDS
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)

    def _session_token(self, cookie_header: str | None) -> str | None:
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except CookieError:
            return None
        morsel = cookie.get(self._cookie_name)
        return morsel.value if morsel else None

    def _cookie_header(self, session_id: str) -> str:
        attributes = [
            f"{self._cookie_name}={session_id}",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
            f"Max-Age={SESSION_TTL_SECONDS}",
        ]
        if self._secure_cookie:
            attributes.append("Secure")
        return "; ".join(attributes)
