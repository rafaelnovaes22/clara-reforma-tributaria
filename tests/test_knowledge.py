from __future__ import annotations

import unittest
from datetime import date

from backend.clara.knowledge import (
    load_source_registry,
    official_https_url,
    retrieve_sources,
    source_registry_is_fresh,
)


class SourceRegistryTests(unittest.TestCase):
    def test_registry_contains_only_canonical_official_https_urls(self) -> None:
        sources = load_source_registry()
        self.assertGreaterEqual(len(sources), 5)
        self.assertTrue(all(official_https_url(source["url"]) for source in sources))
        rfb_source = next(source for source in sources if source["id"] == "RFB2026")
        self.assertTrue(rfb_source["url"].endswith("/orientacoes-2026"))

    def test_registry_expires_without_accountant_review(self) -> None:
        sources = load_source_registry()
        self.assertTrue(source_registry_is_fresh(sources, date(2026, 8, 20), 14))
        self.assertFalse(source_registry_is_fresh(sources, date(2026, 9, 10), 14))

    def test_retrieval_does_not_return_irrelevant_sources(self) -> None:
        sources = load_source_registry()
        self.assertEqual(retrieve_sources("qual é a previsão do tempo?", sources), [])
        ids = [source["id"] for source in retrieve_sources("Simples Nacional NF-e 2027", sources)]
        self.assertIn("ATO4CRONOGRAMA", ids)


if __name__ == "__main__":
    unittest.main()
