from __future__ import annotations

import re
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree

from .contracts import SourceRecord
from .security import RequestValidationError
from .settings import RuntimeSettings

MAX_XML_ELEMENTS = 20_000
MAX_XML_DEPTH = 64
MAX_MONEY = Decimal("1000000000")
CENT = Decimal("0.01")


def triage_xml(payload: dict[str, Any], settings: RuntimeSettings, source: SourceRecord) -> dict[str, Any]:
    content = str(payload.get("content") or "")
    filename = validate_xml_filename(payload.get("filename"))
    validate_synthetic_confirmation(payload, settings)
    validate_xml_size(content, settings.max_xml_bytes)
    reject_unsafe_xml_declarations(content)
    root = parse_xml(content)
    validate_tree_limits(root)
    findings = inspect_nfe_structure(root)
    return build_triage_result(filename, findings, source)


def validate_synthetic_confirmation(payload: dict[str, Any], settings: RuntimeSettings) -> None:
    if not settings.allow_real_xml and payload.get("synthetic") is not True:
        raise RequestValidationError(
            "synthetic_confirmation_required",
            "O piloto aceita apenas XML sintético. Confirme explicitamente que o arquivo não contém dados reais.",
        )


def validate_xml_filename(raw_filename: object) -> str:
    filename = str(raw_filename or "nota.xml").strip()
    invalid_path = "/" in filename or "\\" in filename or ".." in filename
    if invalid_path or len(filename) > 128 or not filename.lower().endswith(".xml"):
        raise RequestValidationError(
            "invalid_filename", "Use um nome simples terminado em .xml, com até 128 caracteres."
        )
    if not re.fullmatch(r"[\w .()-]+\.xml", filename, re.IGNORECASE):
        raise RequestValidationError("invalid_filename", "O nome do XML contém caracteres não permitidos.")
    return filename


def validate_xml_size(content: str, max_bytes: int) -> None:
    try:
        size = len(content.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise RequestValidationError("invalid_xml_encoding", "O XML precisa ser texto UTF-8 válido.") from exc
    if not content:
        raise RequestValidationError("empty_xml", "O XML não pode ficar vazio.")
    if size > max_bytes:
        raise RequestValidationError("xml_too_large", f"O XML possui {size} bytes; o limite é {max_bytes}.")


def reject_unsafe_xml_declarations(content: str) -> None:
    if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", content, re.IGNORECASE):
        raise RequestValidationError("unsafe_xml_declaration", "DTD e entidades não são aceitos na triagem.")


def parse_xml(content: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise RequestValidationError("invalid_xml", f"XML malformado na posição informada pelo parser: {exc}.") from exc


def validate_tree_limits(root: ElementTree.Element) -> None:
    stack: list[tuple[ElementTree.Element, int]] = [(root, 1)]
    count = 0
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > MAX_XML_ELEMENTS or depth > MAX_XML_DEPTH:
            raise RequestValidationError(
                "xml_complexity_limit",
                f"O XML excede {MAX_XML_ELEMENTS} elementos ou profundidade {MAX_XML_DEPTH}.",
            )
        stack.extend((child, depth + 1) for child in element)


def inspect_nfe_structure(root: ElementTree.Element) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    add_root_finding(root, findings)
    inf_nfe = find_first(root, "infnfe")
    if inf_nfe is None:
        add_missing_infnfe_finding(findings)
        return findings
    add_nfe_detail_findings(inf_nfe, findings)
    add_no_alert_finding(findings)
    return findings


def add_missing_infnfe_finding(findings: list[dict[str, str]]) -> None:
    findings.append(
        finding("missing_infnfe", "alto", "Grupo infNFe ausente", "Não foi localizada a estrutura principal da NF-e.")
    )


def add_nfe_detail_findings(inf_nfe: ElementTree.Element, findings: list[dict[str, str]]) -> None:
    add_access_key_finding(inf_nfe, findings)
    add_issuer_finding(inf_nfe, findings)
    add_product_findings(inf_nfe, findings)
    add_total_findings(inf_nfe, findings)
    add_ibs_cbs_findings(inf_nfe, findings)


def add_no_alert_finding(findings: list[dict[str, str]]) -> None:
    if findings:
        return
    findings.append(
        finding(
            "no_limited_triage_alert",
            "informativo",
            "Nenhum alerta na triagem limitada",
            "Isso não valida schema, assinatura, regra tributária nem autorização fiscal.",
        )
    )


def add_root_finding(root: ElementTree.Element, findings: list[dict[str, str]]) -> None:
    if local_name(root.tag) not in {"nfeproc", "nfe"}:
        findings.append(finding("unexpected_root", "alto", "Raiz inesperada", "Era esperada uma raiz nfeProc ou NFe."))


def add_access_key_finding(inf_nfe: ElementTree.Element, findings: list[dict[str, str]]) -> None:
    access_key = str(inf_nfe.attrib.get("Id") or "")
    if not re.fullmatch(r"NFe\d{44}", access_key):
        findings.append(
            finding(
                "invalid_access_key", "alto", "Chave de acesso inválida", "O Id de infNFe não segue NFe + 44 dígitos."
            )
        )


def add_issuer_finding(inf_nfe: ElementTree.Element, findings: list[dict[str, str]]) -> None:
    issuer = find_child(inf_nfe, "emit")
    cnpj = child_text(issuer, "cnpj")
    cpf = child_text(issuer, "cpf")
    valid_document = valid_cnpj(cnpj) or valid_cpf(cpf)
    if not valid_document:
        findings.append(
            finding(
                "invalid_issuer_document",
                "alto",
                "Documento do emitente inválido",
                "Informe CNPJ com 14 dígitos ou CPF com 11 dígitos no grupo emit.",
            )
        )


def add_product_findings(inf_nfe: ElementTree.Element, findings: list[dict[str, str]]) -> None:
    items = find_all(inf_nfe, "det")
    if not items:
        findings.append(finding("missing_items", "alto", "Itens ausentes", "Nenhum grupo det foi localizado."))
        return
    invalid_ncm = 0
    for item in items:
        product = find_child(item, "prod")
        if not re.fullmatch(r"\d{8}", child_text(product, "ncm")):
            invalid_ncm += 1
    if invalid_ncm:
        findings.append(
            finding(
                "invalid_ncm",
                "médio",
                "NCM ausente ou inválido",
                f"{invalid_ncm} item(ns) não possuem NCM com 8 dígitos.",
            )
        )


def add_total_findings(inf_nfe: ElementTree.Element, findings: list[dict[str, str]]) -> None:
    total = find_first(inf_nfe, "icmstot")
    product_total = positive_decimal(child_text(total, "vprod"))
    invoice_total = positive_decimal(child_text(total, "vnf"))
    if product_total is None or invoice_total is None:
        add_invalid_totals_finding(findings)
        return
    item_values = read_item_product_values(inf_nfe)
    if not item_values or any(value is None for value in item_values):
        add_invalid_item_values_finding(findings)
        return
    summed_items = sum((value for value in item_values if value is not None), Decimal("0"))
    if money(summed_items) != money(product_total):
        add_divergent_product_total_finding(findings)


def read_item_product_values(inf_nfe: ElementTree.Element) -> list[Decimal | None]:
    return [positive_decimal(child_text(find_child(item, "prod"), "vprod")) for item in find_all(inf_nfe, "det")]


def add_invalid_totals_finding(findings: list[dict[str, str]]) -> None:
    findings.append(
        finding(
            "invalid_totals",
            "alto",
            "Totais ausentes ou inválidos",
            "vProd e vNF devem ser números positivos no grupo de totais.",
        )
    )


def add_invalid_item_values_finding(findings: list[dict[str, str]]) -> None:
    findings.append(
        finding("invalid_item_values", "alto", "Valores de itens inválidos", "Cada item deve possuir vProd positivo.")
    )


def add_divergent_product_total_finding(findings: list[dict[str, str]]) -> None:
    findings.append(
        finding(
            "divergent_product_total",
            "alto",
            "Total de produtos divergente",
            "A soma limitada dos vProd dos itens diverge do vProd informado em ICMSTot.",
        )
    )


def add_ibs_cbs_findings(inf_nfe: ElementTree.Element, findings: list[dict[str, str]]) -> None:
    ibs_values = element_texts(inf_nfe, {"vibs", "pibs", "cibs"})
    cbs_values = element_texts(inf_nfe, {"vcbs", "pcbs", "ccbs"})
    if not ibs_values or not cbs_values:
        findings.append(
            finding(
                "ibs_cbs_not_detected",
                "médio",
                "Campos IBS/CBS não detectados",
                "A triagem limitada não localizou valores não vazios de IBS e CBS.",
            )
        )


def build_triage_result(
    filename: str,
    findings: list[dict[str, str]],
    source: SourceRecord,
) -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "filename": filename,
        "status": "triagem_pendente",
        "score": None,
        "precheck_only": True,
        "human_review_required": True,
        "schema_validated": False,
        "authorized": False,
        "findings": findings,
        "source": source,
        "note": "Triagem estrutural limitada. Não valida schema oficial, assinatura, cálculo, regra fiscal ou autorização.",
    }


def calculate_split(payload: dict[str, Any], source: SourceRecord) -> dict[str, Any]:
    gross = required_decimal(payload, "gross")
    ibs_rate = required_decimal(payload, "ibs_rate")
    cbs_rate = required_decimal(payload, "cbs_rate")
    validate_split_ranges(gross, ibs_rate, cbs_rate)
    ibs = money(gross * ibs_rate / Decimal("100"))
    cbs = money(gross * cbs_rate / Decimal("100"))
    return {
        "gross": float(money(gross)),
        "ibs": float(ibs),
        "cbs": float(cbs),
        "tax": float(money(ibs + cbs)),
        "net": float(money(gross - ibs - cbs)),
        "rates": {"ibs": float(ibs_rate), "cbs": float(cbs_rate)},
        "precheck_only": True,
        "human_review_required": True,
        "note": "Cálculo matemático com taxas informadas pelo usuário. Não define alíquota nem apuração fiscal.",
        "source": source,
    }


def required_decimal(payload: dict[str, Any], field_name: str) -> Decimal:
    if field_name not in payload:
        raise RequestValidationError("missing_numeric_field", f"O campo {field_name} é obrigatório.")
    try:
        value = Decimal(str(payload[field_name]))
    except (InvalidOperation, ValueError) as exc:
        raise RequestValidationError(
            "invalid_numeric_field", f"{field_name} precisa ser um número decimal finito."
        ) from exc
    if not value.is_finite():
        raise RequestValidationError("invalid_numeric_field", f"{field_name} precisa ser um número decimal finito.")
    return value


def validate_split_ranges(gross: Decimal, ibs_rate: Decimal, cbs_rate: Decimal) -> None:
    if gross <= 0 or gross > MAX_MONEY:
        raise RequestValidationError(
            "invalid_gross", f"gross precisa ser maior que zero e menor ou igual a {MAX_MONEY}."
        )
    for name, rate in (("ibs_rate", ibs_rate), ("cbs_rate", cbs_rate)):
        if rate < 0 or rate > 100:
            raise RequestValidationError("invalid_rate", f"{name} precisa ficar entre 0 e 100.")
    if ibs_rate + cbs_rate > 100:
        raise RequestValidationError("invalid_total_rate", "A soma de ibs_rate e cbs_rate não pode exceder 100.")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def find_first(root: ElementTree.Element, wanted: str) -> ElementTree.Element | None:
    return next((element for element in root.iter() if local_name(element.tag) == wanted), None)


def find_all(root: ElementTree.Element, wanted: str) -> list[ElementTree.Element]:
    return [element for element in root.iter() if local_name(element.tag) == wanted]


def find_child(parent: ElementTree.Element | None, wanted: str) -> ElementTree.Element | None:
    if parent is None:
        return None
    return next((element for element in parent if local_name(element.tag) == wanted), None)


def child_text(parent: ElementTree.Element | None, wanted: str) -> str:
    child = find_child(parent, wanted)
    return (child.text or "").strip() if child is not None else ""


def element_texts(root: ElementTree.Element, wanted: set[str]) -> list[str]:
    return [
        (element.text or "").strip()
        for element in root.iter()
        if local_name(element.tag) in wanted and (element.text or "").strip()
    ]


def positive_decimal(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed > 0 else None


def valid_cnpj(value: str) -> bool:
    if not re.fullmatch(r"\d{14}", value) or len(set(value)) == 1:
        return False
    first = tax_check_digit(value[:12], (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    second = tax_check_digit(value[:12] + first, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return value[-2:] == first + second


def valid_cpf(value: str) -> bool:
    if not re.fullmatch(r"\d{11}", value) or len(set(value)) == 1:
        return False
    first = tax_check_digit(value[:9], tuple(range(10, 1, -1)))
    second = tax_check_digit(value[:9] + first, tuple(range(11, 1, -1)))
    return value[-2:] == first + second


def tax_check_digit(value: str, weights: tuple[int, ...]) -> str:
    remainder = sum(int(digit) * weight for digit, weight in zip(value, weights, strict=True)) % 11
    return str(0 if remainder < 2 else 11 - remainder)


def finding(code: str, severity: str, title: str, detail: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "title": title, "detail": detail}
