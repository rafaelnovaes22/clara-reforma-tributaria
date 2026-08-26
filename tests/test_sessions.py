from __future__ import annotations

import unittest

from backend.clara.security import PilotPrincipal
from backend.clara.sessions import PilotSessionRegistry


class PilotSessionRegistryTests(unittest.TestCase):
    def test_creates_secure_host_cookie_for_pilot(self) -> None:
        registry = PilotSessionRegistry("client", max_sessions=2, secure_cookie=True)
        session, header = registry.resolve_or_create(PilotPrincipal("accountant"), None, now=0)
        self.assertIn("__Host-clara_sid=", header or "")
        self.assertIn("Secure", header or "")
        self.assertIn("HttpOnly", header or "")
        self.assertIn("SameSite=Strict", header or "")
        self.assertTrue(session.csrf_token)

    def test_cookie_is_bound_to_authenticated_actor(self) -> None:
        registry = PilotSessionRegistry("client", max_sessions=2, secure_cookie=False)
        first, header = registry.resolve_or_create(PilotPrincipal("actor-a"), None, now=0)
        cookie = (header or "").split(";", 1)[0]
        self.assertIsNone(registry.resolve_existing(PilotPrincipal("actor-b"), cookie, now=1))
        self.assertEqual(registry.resolve_existing(PilotPrincipal("actor-a"), cookie, now=1), first)

    def test_session_expires_and_registry_stays_bounded(self) -> None:
        registry = PilotSessionRegistry("client", max_sessions=1, secure_cookie=False)
        first, first_header = registry.resolve_or_create(PilotPrincipal("actor"), None, now=0)
        registry.resolve_or_create(PilotPrincipal("other"), None, now=1)
        first_cookie = (first_header or "").split(";", 1)[0]
        self.assertIsNone(registry.resolve_existing(PilotPrincipal("actor"), first_cookie, now=2))
        second, _ = registry.resolve_or_create(PilotPrincipal("actor"), None, now=8000)
        self.assertNotEqual(first.session_id, second.session_id)


if __name__ == "__main__":
    unittest.main()
