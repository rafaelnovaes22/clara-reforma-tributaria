from __future__ import annotations

import unittest

from backend.clara.jev_intent_check import (
    divergence_fields,
    is_configured,
    query_intent_check,
    sanitize_state_text,
)


def fake_post(choice: str, noul: float, confidence: float = 0.9):
    def post(payload: bytes, api_key: str, timeout_s: float):
        from backend.clara.jev_intent_check import parse_response

        return parse_response(
            {
                "model": "jev-1.13.0",
                "answers": {
                    "intent": {"choice": choice, "confidence": confidence},
                    "material": {"noul": noul},
                },
            }
        )

    return post


class SanitizeTests(unittest.TestCase):
    def test_collapses_whitespace_and_truncates(self) -> None:
        self.assertEqual(sanitize_state_text("  saldo   atual "), "saldo atual")
        self.assertEqual(len(sanitize_state_text("a" * 2500)), 2000)
        self.assertEqual(sanitize_state_text(""), "")

    def test_rejects_missing_or_placeholder_key(self) -> None:
        self.assertFalse(is_configured(""))
        self.assertFalse(is_configured("ts-..."))
        self.assertTrue(is_configured("chave-real-123"))


class QueryTests(unittest.TestCase):
    def test_returns_none_when_disabled(self) -> None:
        self.assertIsNone(query_intent_check("qual meu saldo?", api_key="chave-real-123"))

    def test_parses_choice_and_material_noul(self) -> None:
        check = query_intent_check(
            "Preciso destacar IBS na NF-e?",
            api_key="chave-real-123",
            enabled=True,
            post=fake_post("invoice", 0.93),
        )
        self.assertIsNotNone(check)
        assert check is not None
        self.assertEqual(check.choice, "invoice")
        self.assertTrue(check.material)
        self.assertFalse(check.escalate)
        self.assertFalse(check.mocked)

    def test_never_raises_on_transport_failure(self) -> None:
        def boom(payload: bytes, api_key: str, timeout_s: float):
            raise TimeoutError("rede fora")

        self.assertIsNone(query_intent_check("oi", api_key="chave-real-123", enabled=True, post=boom))

    def test_rejects_unknown_choice_and_empty_state(self) -> None:
        self.assertIsNone(
            query_intent_check(
                "oi",
                api_key="chave-real-123",
                enabled=True,
                post=fake_post("TRANSFERIR_TUDO", 0.1),
            )
        )
        called: list = []

        def spy(payload: bytes, api_key: str, timeout_s: float):
            called.append(payload)
            return None

        self.assertIsNone(query_intent_check("   ", api_key="chave-real-123", enabled=True, post=spy))
        self.assertEqual(called, [])


class DivergenceTests(unittest.TestCase):
    def test_silent_on_agreement_and_loud_on_divergence(self) -> None:
        agree = query_intent_check("oi", api_key="chave-real-123", enabled=True, post=fake_post("tax_question", 0.2))
        self.assertIsNone(divergence_fields("tax_question", agree))

        check = query_intent_check(
            "quero contestar",
            api_key="chave-real-123",
            enabled=True,
            post=fake_post("invoice", 0.9),
        )
        fields = divergence_fields("off_topic", check)
        self.assertIsNotNone(fields)
        assert fields is not None
        self.assertEqual(fields["event"], "shadow_divergence")


if __name__ == "__main__":
    unittest.main()
