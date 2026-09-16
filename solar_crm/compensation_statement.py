from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from io import BytesIO

from pypdf import PdfReader


class CompensationStatementError(ValueError):
    pass


@dataclass
class CompensationHistoryRow:
    year: int
    month: int
    period: str
    measured_kwh: float
    irregular_kwh: float
    injected_kwh: float
    compensated_kwh: float
    surplus_kwh: float
    gross_kwh: float


@dataclass
class CompensationMovement:
    period: str
    generation_class: str
    previous_balance_kwh: float
    injected_kwh: float
    received_kwh: float
    compensated_kwh: float
    transferred_kwh: float
    expired_kwh: float
    available_kwh: float
    consumption_kwh: float
    expiration_cycle: str = ""


@dataclass
class CompensationTransfer:
    allocation_pct: float
    unit_code: str
    conventional_kwh: float
    peak_kwh: float
    off_peak_kwh: float
    intermediate_kwh: float
    cycle: str = ""
    beneficiary_name: str = ""

    @property
    def total_kwh(self) -> float:
        return sum((self.conventional_kwh, self.peak_kwh, self.off_peak_kwh, self.intermediate_kwh))


@dataclass
class CompensationCredit:
    year: int
    month: int
    period: str
    previous_balance_kwh: float
    compensated_kwh: float
    available_kwh: float
    expiration: str = ""


@dataclass
class CompensationStatement:
    filename: str
    utility: str = ""
    client_name: str = ""
    voltage_group: str = ""
    unit_code: str = ""
    address: str = ""
    reference_month: str = ""
    history: list[CompensationHistoryRow] = field(default_factory=list)
    movements: list[CompensationMovement] = field(default_factory=list)
    transfers: list[CompensationTransfer] = field(default_factory=list)
    credits: list[CompensationCredit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def _current_history(self) -> list[CompensationHistoryRow]:
        if not self.reference_month:
            return []
        year, month = (int(value) for value in self.reference_month.split("-"))
        return [row for row in self.history if row.year == year and row.month == month]

    @property
    def measured_kwh(self) -> float:
        return sum(row.measured_kwh for row in self._current_history())

    @property
    def injected_kwh(self) -> float:
        return sum(row.injected_kwh for row in self._current_history())

    @property
    def compensated_kwh(self) -> float:
        return sum(row.compensated_kwh for row in self._current_history())

    @property
    def surplus_kwh(self) -> float:
        return sum(row.surplus_kwh for row in self._current_history())

    @property
    def previous_balance_kwh(self) -> float:
        return sum(row.previous_balance_kwh for row in self.movements)

    @property
    def transferred_kwh(self) -> float:
        return sum(abs(row.transferred_kwh) for row in self.movements)

    @property
    def allocated_kwh(self) -> float:
        return sum(row.total_kwh for row in self.transfers)

    @property
    def available_credit_kwh(self) -> float:
        return sum(row.available_kwh for row in self.movements)

    @property
    def expired_kwh(self) -> float:
        return sum(row.expired_kwh for row in self.movements)

    @property
    def compensation_pct(self) -> float:
        return min(100.0, self.compensated_kwh / self.measured_kwh * 100) if self.measured_kwh else 0.0


def _plain(value: str) -> str:
    value = value.replace("�", "?")
    return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))


def _number(value: str) -> float:
    value = value.strip().replace(" ", "")
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    return float(value or 0)


def _extract_pages(content: bytes) -> list[str]:
    try:
        reader = PdfReader(BytesIO(content))
        return [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    except Exception as exc:
        raise CompensationStatementError("Não foi possível abrir o demonstrativo em PDF.") from exc


def _parse_identity(lines: list[str], statement: CompensationStatement) -> None:
    unit_line_index = next((i for i, line in enumerate(lines) if re.search(r"N.mero da UC", line, re.I)), -1)
    if unit_line_index < 0:
        return
    line = lines[unit_line_index]
    match = re.search(r"(.+?)\s*\|\s*N.mero da UC:\s*([\d.\-]+)", line, re.I)
    if match:
        left_and_voltage = match.group(1)
        parts = re.split(r"\s{3,}", left_and_voltage.strip())
        statement.voltage_group = parts[-1].strip() if len(parts) > 1 else ""
        statement.unit_code = match.group(2).strip()
    left_names: list[str] = []
    right_values: list[str] = []
    for candidate in lines[unit_line_index:unit_line_index + 3]:
        columns = re.split(r"\s{3,}", candidate.strip())
        if columns:
            name = re.sub(r"\s*(Media|Baixa|Alta).*?\|.*$", "", columns[0], flags=re.I).strip()
            if name:
                left_names.append(name)
        if len(columns) > 1 and "Numero da UC" not in _plain(columns[-1]):
            right_values.append(columns[-1].strip())
    statement.client_name = " ".join(left_names).strip()
    statement.address = " ".join(right_values).strip()


def _parse_history(text: str, statement: CompensationStatement) -> None:
    matches = list(re.finditer(r"Consumo\s+(Ponta|Fora de Ponta)", text, re.I))
    for index, marker in enumerate(matches):
        period = "Ponta" if marker.group(1).lower() == "ponta" else "Fora de ponta"
        end = matches[index + 1].start() if index + 1 < len(matches) else text.find("Movimenta", marker.end())
        block = text[marker.end(): end if end >= 0 else len(text)]
        for row in re.finditer(
            r"(?m)^\s*(20\d{2})\s+(\d{2})\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$",
            block,
        ):
            values = [_number(value) for value in row.groups()[2:]]
            statement.history.append(CompensationHistoryRow(int(row.group(1)), int(row.group(2)), period, *values))


def _parse_movements(text: str, statement: CompensationStatement) -> None:
    start = text.find("Movimenta")
    end = text.find("Discrimina", start)
    if start < 0:
        return
    block = text[start:end if end >= 0 else len(text)]
    period = ""
    for line in block.splitlines():
        stripped = line.strip()
        if stripped in {"Conv", "Pt", "FPt", "Itmdr"}:
            period = {"Conv": "Convencional", "Pt": "Ponta", "FPt": "Fora de ponta", "Itmdr": "Intermediário"}[stripped]
            continue
        match = re.match(r"GD\s+(I{1,3})\s+(.+)$", stripped)
        if not match or not period:
            continue
        tokens = match.group(2).split()
        cycle = tokens[-1] if tokens and re.fullmatch(r"\d{2}/\d{4}", tokens[-1]) else ""
        if cycle:
            tokens = tokens[:-1]
        if len(tokens) < 8:
            continue
        values = [_number(value) for value in tokens[:8]]
        statement.movements.append(CompensationMovement(period, f"GD {match.group(1)}", *values, expiration_cycle=cycle))


def _parse_transfers(text: str, statement: CompensationStatement) -> None:
    start = text.find("Discrimina")
    end = text.find("Composi", start)
    if start < 0:
        return
    block = text[start:end if end >= 0 else len(text)]
    pattern = re.compile(r"(?m)^\s*(\d+(?:[.,]\d+)?)\s+(\d{8,})\s+((?:-?[\d.,]+\s+){11}-?[\d.,]+)\s+(\d{2}/\d{4})\s*$")
    for match in pattern.finditer(block):
        values = [_number(value) for value in match.group(3).split()]
        periods = [sum(abs(value) for value in values[i:i + 3]) for i in range(0, 12, 3)]
        statement.transfers.append(CompensationTransfer(_number(match.group(1)), match.group(2), *periods, cycle=match.group(4)))


def _parse_credits(text: str, statement: CompensationStatement) -> None:
    start = text.find("Composi")
    if start < 0:
        return
    year = month = 0
    expiration = ""
    for line in text[start:].splitlines():
        match = re.match(r"\s*(?:(20\d{2})\s+(\d{2})\s+)?(Conv|Pt|FPt|Itmdr)\s+(.+)$", line)
        if not match:
            continue
        if match.group(1):
            year, month = int(match.group(1)), int(match.group(2))
        tokens = match.group(4).split()
        if tokens and re.fullmatch(r"\d{2}/\d{4}", tokens[-1]):
            expiration = tokens.pop()
        if not year or len(tokens) < 9:
            continue
        values = [_number(value) for value in tokens[:9]]
        period = {"Conv": "Convencional", "Pt": "Ponta", "FPt": "Fora de ponta", "Itmdr": "Intermediário"}[match.group(3)]
        statement.credits.append(CompensationCredit(year, month, period, sum(values[:3]), sum(values[3:6]), sum(values[6:9]), expiration))


def analyze_compensation_statement(content: bytes, filename: str = "demonstrativo.pdf") -> CompensationStatement:
    if not content:
        raise CompensationStatementError("Envie um demonstrativo de compensação em PDF.")
    pages = _extract_pages(content)
    original = "\n".join(pages)
    text = _plain(original)
    if "Demonstrativo de Compensa" not in text:
        raise CompensationStatementError("O PDF não parece ser um Demonstrativo de Compensação de Energia da Energisa.")
    statement = CompensationStatement(filename=filename)
    lines = text.splitlines()
    statement.utility = next((line.strip() for line in lines if "DISTRIBUIDORA DE ENERGIA" in line.upper()), "Energisa")
    _parse_identity(lines, statement)
    reference = re.search(r"Refer.ncia:\s*(\d{2})/(\d{4})", text, re.I)
    if reference:
        statement.reference_month = f"{reference.group(2)}-{reference.group(1)}"
    _parse_history(text, statement)
    _parse_movements(text, statement)
    _parse_transfers(text, statement)
    _parse_credits(text, statement)
    if not statement.history:
        statement.warnings.append("O histórico mensal não foi identificado; confira o PDF original.")
    if not statement.transfers:
        statement.warnings.append("Nenhuma unidade beneficiária foi identificada no rateio deste ciclo.")
    if statement.transfers and abs(statement.allocated_kwh - statement.transferred_kwh) > 1:
        statement.warnings.append("O total distribuído às beneficiárias difere do total transferido no movimento mensal.")
    return statement
