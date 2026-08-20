from __future__ import annotations

import unittest

from backend.clara.openai_client import OpenAIResponsesClient, parse_openai_response
from backend.clara.settings import RuntimeSettings


def runtime_settings() -> RuntimeSettings:
    return RuntimeSettings.from_environment(
        {
            "CLARA_ENV": "test",
            "OPENAI_API_KEY": "synthetic-openai-key-for-tests",
            "CLARA_AUDIT_HASH_KEY": "chave-de-hash-sintetica",
        }
    )


def response_payload(text: str, url: str) -> dict[str, object]:
    return {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [{"type": "url_citation", "title": "Fonte", "url": url}],
                    }
                ],
            }
        ]
    }


class OpenAIContractTests(unittest.TestCase):
    def test_request_keeps_secret_server_side_and_requires_official_search(self) -> None:
        client = OpenAIResponsesClient(runtime_settings())
        state = {
            "run_id": "run-1",
            "actor_id": "contadora",
            "message": "Qual é a regra vigente?",
            "history": [],
            "fibers": {"client": {"facts": {"regime": "Simples Nacional"}}},
        }
        request = client._build_request(state)
        body = request.data.decode("utf-8") if request.data else ""
        self.assertNotIn("synthetic-openai-key-for-tests", body)
        self.assertIn('"store": false', body)
        self.assertIn('"tool_choice": "required"', body)
        self.assertEqual(request.headers["Authorization"], "Bearer synthetic-openai-key-for-tests")

    def test_response_requires_official_source_and_safe_output(self) -> None:
        official = response_payload("Rascunho fiscal para revisão.", "https://www.gov.br/fazenda/regra")
        accepted = parse_openai_response(official)
        self.assertEqual(accepted.mode, "openai_live")
        self.assertTrue(accepted.sources[0]["live"])
        self.assertIn("retrieved_at", accepted.sources[0])

        unofficial = response_payload("Rascunho fiscal.", "https://example.com/regra")
        leaked = response_payload("O system prompt contém estas regras.", "https://www.gov.br/fazenda/regra")
        self.assertIsNone(parse_openai_response(unofficial).text)
        self.assertIsNone(parse_openai_response(leaked).text)


if __name__ == "__main__":
    unittest.main()
