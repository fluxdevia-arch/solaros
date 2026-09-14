from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from io import BytesIO
from typing import Iterable

from pypdf import PdfReader


MONTHS = {
    "JANEIRO": 1,
    "FEVEREIRO": 2,
    "MARCO": 3,
    "ABRIL": 4,
    "MAIO": 5,
    "JUNHO": 6,
    "JULHO": 7,
    "AGOSTO": 8,
    "SETEMBRO": 9,
    "OUTUBRO": 10,
    "NOVEMBRO": 11,
    "DEZEMBRO": 12,
}

MONTH_ABBR = {"JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"}


class BillAuditError(ValueError):
    pass


@dataclass(frozen=True)
class BillItem:
    description: str
    unit: str = ""
    quantity: float | None = None
    unit_price: float | None = None
    amount: float = 0.0
    icms: float | None = None


@dataclass
class BillAudit:
    source_filename: str
    utility: str = "Energisa Paraíba"
    client_name: str = ""
    address: str = ""
    unit_code: str = ""
    reference_month: str = ""
    due_date: str = ""
    issue_date: str = ""
    invoice_number: str = ""
    invoice_amount: float = 0.0
    classification: str = ""
    connection: str = ""
    unit_profile: str = "Não identificado"
    billing_days: int = 0
    consumption_kwh: float = 0.0
    injected_measured_kwh: float | None = None
    compensated_kwh: float = 0.0
    compensated_percentage: float = 0.0
    credit_balance_kwh: float = 0.0
    credit_balance_peak_kwh: float = 0.0
    credit_balance_off_peak_kwh: float = 0.0
    gross_consumption_cost: float = 0.0
    solar_credit_value: float = 0.0
    fio_b_value: float = 0.0
    icms_base: float = 0.0
    icms_value: float = 0.0
    pis_value: float = 0.0
    cofins_value: float = 0.0
    distribution_use_charge: float = 0.0
    estimated_without_solar: float = 0.0
    estimated_savings_month: float = 0.0
    estimated_savings_year: float = 0.0
    estimated_savings_5_years: float = 0.0
    historical_average_kwh: float = 0.0
    historical_consumption_kwh: list[tuple[str, float]] = field(default_factory=list)
    previous_month_label: str = ""
    previous_month_consumption_kwh: float = 0.0
    consumption_variation_pct: float | None = None
    items: list[BillItem] = field(default_factory=list)
    findings: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _ascii(value: str) -> str:
    value = value.replace("�", "")
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _number(value: str | None) -> float:
    if not value:
        return 0.0
    clean = re.sub(r"[^0-9,.-]", "", value.strip())
    if not clean or clean in {"-", ".", ","}:
        return 0.0
    if "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return 0.0


def _numbers(value: str) -> list[float]:
    return [_number(item) for item in re.findall(r"-?\d[\d.]*,\d+|-?\d+", value)]


def _clean_label(value: str) -> str:
    normalized = _ascii(value)
    repairs = {
        "CONTRIBUIAO": "Contribuição",
        "ATUALIZAO MONETRIA": "Atualização monetária",
        "Energia Reativa Exced": "Energia reativa excedente",
        "Potncia": "Potência",
    }
    for broken, repaired in repairs.items():
        if broken.upper() in normalized.upper():
            return repaired + normalized.upper().split(broken.upper(), 1)[1].lower()
    return re.sub(r"\s+", " ", normalized).strip()


def _extract_layout(pdf_data: bytes) -> tuple[str, str]:
    try:
        reader = PdfReader(BytesIO(pdf_data))
    except Exception as exc:
        raise BillAuditError("Não foi possível abrir o PDF. Envie a fatura original da Energisa, sem senha.") from exc
    if not reader.pages:
        raise BillAuditError("O PDF não possui páginas legíveis.")
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text(extraction_mode="layout") or page.extract_text() or "")
        except Exception:
            pages.append(page.extract_text() or "")
    combined = "\n".join(pages)
    if len(combined.strip()) < 100:
        raise BillAuditError(
            "O PDF não contém texto pesquisável. Baixe a segunda via original no portal da Energisa; fotos e digitalizações exigem OCR."
        )
    return pages[0], "\n".join(pages[1:])


def _split_columns(line: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s{2,}", line.strip()) if part.strip()]


def _parse_items(page: str) -> list[BillItem]:
    upper = _ascii(page).upper()
    start = upper.find("ITENS DA FATURA")
    end = upper.find("TOTAL:", start)
    if start < 0 or end < 0:
        return []
    block = page[start:end]
    recognized = (
        "CONSUMO EM KWH", "ENERGIA ATV INJETADA", "AJUSTE GDII", "ADIC. B.",
        "CONTRIBUI", "BONUS", "MULTA", "ATUALIZA", "JUROS", "DEMANDA",
        "ENERGIA REATIVA", "CUSTO DE DISPONIBILIDADE", "ENCARGO",
    )
    structured = ("CONSUMO EM KWH", "ENERGIA ATV INJETADA", "AJUSTE GDII", "DEMANDA", "ENERGIA REATIVA")
    items: list[BillItem] = []
    for raw_line in block.splitlines()[1:]:
        parts = _split_columns(raw_line)
        if len(parts) < 2:
            continue
        normalized_description = _ascii(parts[0]).upper()
        if not normalized_description.startswith(recognized):
            continue
        unit = ""
        value_index = 1
        if parts[1].upper() in {"KWH", "KW", "KVARH", "UN"}:
            unit = parts[1].upper()
            value_index = 2
        numeric_parts = parts[value_index:]
        if not numeric_parts:
            continue
        description = _clean_label(parts[0])
        if re.fullmatch(r"\d{2}/\d{4}", numeric_parts[0]):
            description = f"{description} {numeric_parts.pop(0)}"
        if not numeric_parts:
            continue
        if normalized_description.startswith(structured) and len(numeric_parts) >= 3:
            quantity = _number(numeric_parts[0])
            unit_price = _number(numeric_parts[1])
            amount = _number(numeric_parts[2])
            icms = _number(numeric_parts[6]) if len(numeric_parts) > 6 else None
            items.append(BillItem(description, unit or ("kWh" if "KWH" in normalized_description else ""), quantity, unit_price, amount, icms))
        else:
            items.append(BillItem(description, unit, None, None, _number(numeric_parts[0]), None))
    return items


def _tax(page: str, label: str) -> tuple[float, float, float]:
    match = re.search(rf"\b{label}\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$", page, re.MULTILINE | re.IGNORECASE)
    if not match:
        return 0.0, 0.0, 0.0
    return _number(match.group(1)), _number(match.group(2)), _number(match.group(3))


def _meter_totals(page_two: str) -> tuple[float, float | None]:
    consumed = 0.0
    injected = 0.0
    found_injection = False
    for line in page_two.splitlines():
        normalized = _ascii(line)
        match = re.search(r"\b(KWH|INJ)\s+(?:Fora\s+Ponta|FPonta|Ponta)\s+(.+)$", normalized, re.IGNORECASE)
        if not match:
            continue
        values = _numbers(match.group(2))
        if len(values) < 2:
            continue
        measured = values[-2]
        if match.group(1).upper() == "INJ":
            injected += measured
            found_injection = True
        else:
            consumed += measured
    return consumed, injected if found_injection else None


def _history(page_two: str, group_a: bool) -> list[tuple[str, float]]:
    history: list[tuple[str, float]] = []
    for line in page_two.splitlines():
        normalized = _ascii(line)
        match = re.search(r"\b(" + "|".join(sorted(MONTH_ABBR)) + r")/(\d{2})\s+(.+)$", normalized, re.IGNORECASE)
        if not match:
            continue
        values = _numbers(match.group(3))
        if not values:
            continue
        if group_a and len(values) < 3:
            continue
        consumption = values[0] + (values[2] if group_a else 0.0)
        history.append((f"{match.group(1).upper()}/{match.group(2)}", round(consumption, 3)))
    return history


def _payer_details(page: str) -> tuple[str, str]:
    lines = page.splitlines()
    for index, line in enumerate(lines):
        if _ascii(line).strip().upper().startswith("PAGADOR"):
            values: list[str] = []
            for candidate in lines[index + 1:index + 8]:
                left = re.split(r"\s{12,}", candidate.strip(), maxsplit=1)[0].strip()
                normalized = _ascii(left).upper()
                if not left:
                    continue
                if normalized.startswith(("SACADOR", "AUTENTICACAO", "FICHA DE")):
                    break
                values.append(re.sub(r"\s+", " ", _ascii(left)).strip())
                if len(values) == 2:
                    return values[0], values[1]
    return "", ""


def _findings(audit: BillAudit) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    penalties = sum(
        item.amount for item in audit.items
        if any(term in _ascii(item.description).upper() for term in ("MULTA", "JUROS", "ATUALIZACAO"))
    )
    unused_demand = [item for item in audit.items if "NAO CONSUMIDA" in _ascii(item.description).upper()]
    reactive = [item for item in audit.items if "REATIVA" in _ascii(item.description).upper()]
    if unused_demand:
        cost = sum(item.amount for item in unused_demand)
        quantity = sum(item.quantity or 0 for item in unused_demand)
        findings.append({
            "severity": "Alta",
            "title": "Demanda contratada não utilizada",
            "evidence": f"{quantity:.2f} kW cobrados, com impacto de R$ {cost:.2f} no ciclo.",
            "recommendation": "Revisar demanda contratada e modalidade tarifária com estudo de cargas e histórico de 12 meses.",
        })
    if reactive:
        cost = sum(item.amount for item in reactive)
        quantity = sum(item.quantity or 0 for item in reactive)
        findings.append({
            "severity": "Atenção",
            "title": "Energia reativa excedente",
            "evidence": f"{quantity:.2f} kvarh/unidades e cobrança de R$ {cost:.2f}.",
            "recommendation": "Avaliar fator de potência, banco de capacitores e horários de maior excedente.",
        })
    if penalties > 0:
        findings.append({
            "severity": "Atenção",
            "title": "Encargos por atraso",
            "evidence": f"Multas, juros e atualização monetária somam R$ {penalties:.2f}.",
            "recommendation": "Regularizar o vencimento ou débito automático para eliminar custos evitáveis.",
        })
    if audit.fio_b_value > 0:
        findings.append({
            "severity": "Informativa",
            "title": "Parcela de transição GD II / Fio B",
            "evidence": f"A fatura apresenta R$ {audit.fio_b_value:.2f} de ajuste associado à Lei 14.300/2022.",
            "recommendation": "Acompanhar a evolução anual da cobrança e separar esse efeito ao comparar economias entre períodos.",
        })
    if audit.solar_credit_value > 0:
        findings.append({
            "severity": "Positiva",
            "title": "Créditos solares reconhecidos",
            "evidence": f"Foram compensados {audit.compensated_kwh:.2f} kWh, equivalentes a R$ {audit.solar_credit_value:.2f} antes do Fio B.",
            "recommendation": "Conferir mensalmente a origem, o rateio e o saldo de créditos das unidades participantes.",
        })
    if audit.historical_average_kwh > 0:
        variation = (audit.consumption_kwh / audit.historical_average_kwh - 1) * 100
        if abs(variation) >= 20:
            findings.append({
                "severity": "Atenção" if variation > 0 else "Informativa",
                "title": "Consumo fora da média histórica",
                "evidence": f"O consumo do ciclo ficou {abs(variation):.1f}% {'acima' if variation > 0 else 'abaixo'} da média exibida na fatura.",
                "recommendation": "Validar sazonalidade, quantidade de dias faturados, mudança de carga e eventuais estimativas de leitura.",
            })
    if not findings:
        findings.append({
            "severity": "Informativa",
            "title": "Sem inconsistência evidente nos campos extraídos",
            "evidence": "Os totais e componentes principais foram reconhecidos no documento.",
            "recommendation": "Manter a conferência mensal e comparar com medidores, portal de geração e demonstrativo de créditos.",
        })
    return findings


def analyze_energisa_bill(pdf_data: bytes, filename: str = "fatura.pdf") -> BillAudit:
    if not pdf_data:
        raise BillAuditError("Envie uma fatura em PDF.")
    first_page, remaining_pages = _extract_layout(pdf_data)
    first_ascii = _ascii(first_page)
    remaining_ascii = _ascii(remaining_pages)
    all_ascii = f"{first_ascii}\n{remaining_ascii}"
    if "ENERGISA" not in all_ascii.upper():
        raise BillAuditError("O arquivo não foi reconhecido como uma fatura da Energisa.")

    audit = BillAudit(source_filename=filename)
    audit.items = _parse_items(first_page)

    reference = re.search(
        r"(" + "|".join(MONTHS) + r")\s*/\s*(20\d{2})\s+(\d{2}/\d{2}/20\d{2})\s+R\$\s*([\d.,]+)",
        first_ascii,
        re.IGNORECASE,
    )
    if reference:
        month = MONTHS[reference.group(1).upper()]
        audit.reference_month = f"{reference.group(2)}-{month:02d}"
        audit.due_date = reference.group(3)
        audit.invoice_amount = _number(reference.group(4))

    issue = re.search(r"DATA DE EMISSAO:\s*(\d{2}/\d{2}/20\d{2})", first_ascii, re.IGNORECASE)
    audit.issue_date = issue.group(1) if issue else ""
    invoice_number = re.search(r"NOTA FISCAL N.?\s*:\s*([\d.]+)", first_ascii, re.IGNORECASE)
    audit.invoice_number = invoice_number.group(1) if invoice_number else ""
    document = re.search(r"\b(\d{6,})-(20\d{2})-(\d{2})-\d\b", first_ascii)
    audit.unit_code = document.group(1) if document else ""

    classification_lines = []
    lines = first_ascii.splitlines()
    for index, line in enumerate(lines):
        if "Classifica" in line:
            classification_lines.append(_split_columns(line)[0])
            if index + 1 < len(lines):
                continuation = _split_columns(lines[index + 1])
                if continuation and not any(word in continuation[0].upper() for word in ("TENSAO", "LIGACAO")):
                    classification_lines.append(continuation[0])
            break
    audit.classification = " ".join(classification_lines).replace("Classificao:", "").replace("Classificacao:", "").strip()
    connection = re.search(r"LIGAO:\s*([A-Z]+)|LIGACAO:\s*([A-Z]+)", first_ascii, re.IGNORECASE)
    audit.connection = next((group for group in connection.groups() if group), "") if connection else ""

    audit.client_name, audit.address = _payer_details(first_page)

    group_a = bool(re.search(r"/\s*A\d", audit.classification, re.IGNORECASE))
    has_same_unit_credit = any("MUC" in _ascii(item.description).upper() for item in audit.items)
    if group_a and "MICROGERA" in remaining_ascii.upper():
        audit.unit_profile = "Geradora - Grupo A"
    elif has_same_unit_credit:
        audit.unit_profile = "Geradora - baixa tensão"
    elif "UC DE COMPENSA" in remaining_ascii.upper():
        audit.unit_profile = "Unidade beneficiária"
    elif group_a:
        audit.unit_profile = "Grupo A"

    total = re.search(r"TOTAL:\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", first_ascii, re.IGNORECASE)
    if total:
        audit.invoice_amount = audit.invoice_amount or _number(total.group(1))
        audit.icms_base = _number(total.group(3))
        audit.icms_value = _number(total.group(4))
    _, _, audit.pis_value = _tax(first_page, "PIS")
    _, _, audit.cofins_value = _tax(first_page, "COFINS")

    days = re.search(r"Dias:\s*(\d+)", remaining_ascii, re.IGNORECASE)
    audit.billing_days = int(days.group(1)) if days else 0
    eusd = re.search(r"Encargo de Uso do Sistema de Distribui.*?R\$\s*([\d.,]+)", remaining_ascii, re.IGNORECASE | re.DOTALL)
    audit.distribution_use_charge = _number(eusd.group(1)) if eusd else 0.0

    consumption_items = [item for item in audit.items if _ascii(item.description).upper().startswith("CONSUMO EM KWH")]
    injected_items = [item for item in audit.items if _ascii(item.description).upper().startswith("ENERGIA ATV INJETADA")]
    audit.compensated_kwh = round(sum(item.quantity or 0 for item in injected_items), 3)
    audit.gross_consumption_cost = round(sum(max(item.amount, 0) for item in consumption_items), 2)
    audit.solar_credit_value = round(abs(sum(min(item.amount, 0) for item in injected_items)), 2)
    audit.fio_b_value = round(sum(
        max(item.amount, 0) for item in audit.items
        if "AJUSTE GDII" in _ascii(item.description).upper() or "FIO B" in _ascii(item.description).upper()
    ), 2)

    measured_consumption, measured_injection = _meter_totals(remaining_pages)
    audit.consumption_kwh = round(measured_consumption or sum(item.quantity or 0 for item in consumption_items), 3)
    audit.injected_measured_kwh = round(measured_injection, 3) if measured_injection is not None else None

    balances = re.search(r"Saldo Ac:\s*([\d.,]+)\(P\)\s*([\d.,]+)\(FP\)", remaining_ascii, re.IGNORECASE)
    if balances:
        audit.credit_balance_peak_kwh = _number(balances.group(1))
        audit.credit_balance_off_peak_kwh = _number(balances.group(2))
        audit.credit_balance_kwh = audit.credit_balance_peak_kwh + audit.credit_balance_off_peak_kwh
    else:
        balance = re.search(r"Saldo Acumulado:\s*([\d.,]+)", remaining_ascii, re.IGNORECASE)
        if balance:
            raw_balance = balance.group(1)
            audit.credit_balance_kwh = _number(raw_balance.replace(".", "") if "," not in raw_balance else raw_balance)

    audit.historical_consumption_kwh = _history(remaining_pages, group_a)
    historical_values = [value for _, value in audit.historical_consumption_kwh]
    audit.historical_average_kwh = round(sum(historical_values) / len(historical_values), 2) if historical_values else 0.0
    if len(audit.historical_consumption_kwh) >= 2:
        audit.previous_month_label, audit.previous_month_consumption_kwh = audit.historical_consumption_kwh[1]

    audit.estimated_savings_month = round(max(audit.solar_credit_value - audit.fio_b_value, 0.0), 2)
    audit.estimated_without_solar = round(audit.invoice_amount + audit.estimated_savings_month, 2)
    audit.estimated_savings_year = round(audit.estimated_savings_month * 12, 2)
    audit.estimated_savings_5_years = round(audit.estimated_savings_month * 60, 2)
    if audit.injected_measured_kwh is None and audit.unit_profile.startswith("Geradora"):
        audit.warnings.append("A energia injetada medida não aparece no quadro de medição; foi mantida apenas a energia compensada nos itens da fatura.")
    if audit.unit_profile.startswith("Geradora"):
        audit.warnings.append("A fatura não mede a energia autoconsumida instantaneamente. A economia estimada considera apenas créditos e cobranças visíveis no documento.")
    audit.warnings.append("Projeções anuais e de cinco anos repetem o resultado deste ciclo, sem inflação, reajuste tarifário, degradação ou sazonalidade.")
    return recalculate_audit(audit)


def recalculate_audit(audit: BillAudit) -> BillAudit:
    """Refresh derived financial projections and findings after a manual review."""
    audit.estimated_savings_month = round(max(audit.solar_credit_value - audit.fio_b_value, 0.0), 2)
    audit.estimated_without_solar = round(audit.invoice_amount + audit.estimated_savings_month, 2)
    audit.estimated_savings_year = round(audit.estimated_savings_month * 12, 2)
    audit.estimated_savings_5_years = round(audit.estimated_savings_month * 60, 2)
    if audit.previous_month_consumption_kwh > 0:
        audit.consumption_variation_pct = round(
            (audit.consumption_kwh / audit.previous_month_consumption_kwh - 1) * 100,
            2,
        )
    else:
        audit.consumption_variation_pct = None
    audit.compensated_percentage = round(
        audit.compensated_kwh / audit.consumption_kwh * 100,
        2,
    ) if audit.consumption_kwh > 0 else 0.0
    if audit.credit_balance_peak_kwh or audit.credit_balance_off_peak_kwh:
        audit.credit_balance_kwh = round(audit.credit_balance_peak_kwh + audit.credit_balance_off_peak_kwh, 3)
    audit.findings = _findings(audit)
    return audit


def items_as_rows(items: Iterable[BillItem]) -> list[dict]:
    return [asdict(item) for item in items]
