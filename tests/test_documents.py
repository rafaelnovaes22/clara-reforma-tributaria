from __future__ import annotations

import unittest

from backend.clara.documents import calculate_split, triage_xml
from backend.clara.knowledge import load_source_registry
from backend.clara.security import RequestValidationError
from backend.clara.settings import RuntimeSettings

SETTINGS = RuntimeSettings.from_environment({"CLARA_ENV": "test", "CLARA_MAX_XML_BYTES": "16384"})
LARGE_SETTINGS = RuntimeSettings.from_environment({"CLARA_ENV": "test", "CLARA_MAX_XML_BYTES": "524288"})
SOURCES = {source["id"]: source for source in load_source_registry()}


def synthetic_payload(content: str, filename: str = "nota.xml") -> dict[str, object]:
    return {"filename": filename, "content": content, "synthetic": True}


class XmlTriageTests(unittest.TestCase):
    def test_empty_tags_can_never_be_approved(self) -> None:
        xml = "<nfeProc><NFe><infNFe><emit><CNPJ/></emit><det><prod><NCM/></prod></det><ICMSTot><vProd/><vNF/></ICMSTot><vIBS/><vCBS/></infNFe></NFe></nfeProc>"
        result = triage_xml(synthetic_payload(xml), SETTINGS, SOURCES["RFB2026"])
        self.assertEqual(result["status"], "triagem_pendente")
        self.assertIsNone(result["score"])
        self.assertTrue(result["precheck_only"])
        self.assertTrue(result["human_review_required"])
        self.assertFalse(result["schema_validated"])
        self.assertFalse(result["authorized"])
        codes = {finding["code"] for finding in result["findings"]}
        self.assertIn("invalid_issuer_document", codes)
        self.assertIn("invalid_totals", codes)
        self.assertIn("ibs_cbs_not_detected", codes)

    def test_requires_explicit_synthetic_confirmation(self) -> None:
        with self.assertRaisesRegex(RequestValidationError, "apenas XML sintético"):
            triage_xml({"filename": "nota.xml", "content": "<NFe/>"}, SETTINGS, SOURCES["RFB2026"])

    def test_rejects_dtd_and_entities_before_parsing(self) -> None:
        xml = "<!DOCTYPE x [<!ENTITY a 'x'>]><NFe>&a;</NFe>"
        with self.assertRaises(RequestValidationError) as context:
            triage_xml(synthetic_payload(xml), SETTINGS, SOURCES["RFB2026"])
        self.assertEqual(context.exception.code, "unsafe_xml_declaration")

    def test_rejects_path_like_filename_and_oversized_xml(self) -> None:
        with self.assertRaises(RequestValidationError):
            triage_xml(synthetic_payload("<NFe/>", "../../nota.xml"), SETTINGS, SOURCES["RFB2026"])
        with self.assertRaises(RequestValidationError) as context:
            triage_xml(synthetic_payload("<NFe>" + "x" * 17000 + "</NFe>"), SETTINGS, SOURCES["RFB2026"])
        self.assertEqual(context.exception.code, "xml_too_large")

    def test_unexpected_root_is_always_reported(self) -> None:
        result = triage_xml(synthetic_payload("<fake><infNFe/></fake>"), SETTINGS, SOURCES["RFB2026"])
        codes = {finding["code"] for finding in result["findings"]}
        self.assertIn("unexpected_root", codes)

    def test_rejects_excessive_depth_and_element_count(self) -> None:
        too_deep = "<NFe>" + "<x>" * 64 + "</x>" * 64 + "</NFe>"
        too_many = "<NFe>" + "<x/>" * 20_001 + "</NFe>"
        for xml in (too_deep, too_many):
            with self.subTest(size=len(xml)), self.assertRaises(RequestValidationError) as context:
                triage_xml(synthetic_payload(xml), LARGE_SETTINGS, SOURCES["RFB2026"])
            self.assertEqual(context.exception.code, "xml_complexity_limit")

    def test_validates_document_digits_and_item_total(self) -> None:
        xml = (
            '<nfeProc><NFe><infNFe Id="NFe12345678901234567890123456789012345678901234">'
            "<emit><CNPJ>00000000000000</CNPJ></emit>"
            "<det><prod><NCM>09012100</NCM><vProd>10.00</vProd></prod><vIBS>1</vIBS><vCBS>1</vCBS></det>"
            "<total><ICMSTot><vProd>20.00</vProd><vNF>20.00</vNF></ICMSTot></total>"
            "</infNFe></NFe></nfeProc>"
        )
        result = triage_xml(synthetic_payload(xml), SETTINGS, SOURCES["RFB2026"])
        codes = {finding["code"] for finding in result["findings"]}
        self.assertIn("invalid_issuer_document", codes)
        self.assertIn("divergent_product_total", codes)


class SplitCalculationTests(unittest.TestCase):
    def test_uses_only_explicit_user_rates(self) -> None:
        result = calculate_split({"gross": 100, "ibs_rate": 0.1, "cbs_rate": 0.9}, SOURCES["LC214"])
        self.assertEqual(result["tax"], 1.0)
        self.assertEqual(result["net"], 99.0)
        self.assertTrue(result["human_review_required"])

    def test_rejects_missing_nonfinite_negative_or_excessive_values(self) -> None:
        invalid_payloads = (
            {"gross": 100, "ibs_rate": 0.1},
            {"gross": "NaN", "ibs_rate": 0.1, "cbs_rate": 0.9},
            {"gross": -1, "ibs_rate": 0.1, "cbs_rate": 0.9},
            {"gross": 100, "ibs_rate": 70, "cbs_rate": 40},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(RequestValidationError):
                calculate_split(payload, SOURCES["LC214"])


if __name__ == "__main__":
    unittest.main()
