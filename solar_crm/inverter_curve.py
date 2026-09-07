from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from io import BytesIO
from typing import Any

import pandas as pd

from solar_crm.db import execute, query


class CurveAnalysisError(ValueError):
    """Raised when an inverter export cannot be interpreted safely."""


@dataclass(frozen=True)
class CurveIssue:
    severity: str
    parameter: str
    finding: str
    possible_cause: str
    recommendation: str


FIELD_LABELS = {
    "timestamp": "Data/hora",
    "active_power_kw": "Potência ativa (kW)",
    "pv_power_kw": "Potência FV (kW)",
    "daily_energy_kwh": "Geração do dia (kWh)",
    "frequency_hz": "Frequência da rede (Hz)",
    "grid_voltage_v": "Tensão da rede (V)",
    "heatsink_temp_c": "Temperatura do inversor/radiador (°C)",
    "internal_temp_c": "Temperatura interna (°C)",
    "insulation_kohm": "Resistência de isolamento (kΩ)",
    "leakage_ma": "Corrente de fuga (mA)",
    "power_factor": "Fator de potência",
}

ALIASES = {
    "timestamp": ("data hh mm", "data hora", "timestamp", "date time", "horario", "hora"),
    "active_power_kw": ("potencia ativa", "active power", "pac", "ac output power", "output power"),
    "pv_power_kw": ("potencia pv total", "potencia fv total", "pv power", "dc input power", "input power"),
    "daily_energy_kwh": ("geracao hoje", "energia hoje", "daily yield", "today yield", "e day", "yield today"),
    "frequency_hz": ("frequencia da rede", "grid frequency", "ac frequency", "fac"),
    "grid_voltage_v": ("tensao fase a", "tensao da rede", "grid voltage", "ac voltage", "vac"),
    "heatsink_temp_c": ("temperatura radiador", "temperatura dissipador", "heatsink temperature", "inverter temperature"),
    "internal_temp_c": ("temperatura interna", "internal temperature", "ambient temperature"),
    "insulation_kohm": ("resistencia de isolamento", "insulation resistance", "riso"),
    "leakage_ma": ("corrente de fuga", "leakage current", "residual current"),
    "power_factor": ("fator de potencia", "power factor", "cos phi"),
}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _match_score(column: str, alias: str) -> int:
    normalized = _norm(column)
    alias = _norm(alias)
    if normalized == alias:
        return 100
    if alias in normalized:
        return 80 + min(len(alias), 19)
    tokens = set(alias.split())
    overlap = len(tokens & set(normalized.split()))
    return int(60 * overlap / len(tokens)) if tokens else 0


def suggest_column_mapping(columns: list[object]) -> dict[str, str]:
    """Map semantic fields by header text; column order is deliberately ignored."""
    available = [str(column) for column in columns]
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for field, aliases in ALIASES.items():
        candidates = [
            (max(_match_score(column, alias) for alias in aliases), column)
            for column in available
            if column not in used
        ]
        score, column = max(candidates, default=(0, ""))
        if score >= 72:
            mapping[field] = column
            used.add(column)

    for column in available:
        normalized = _norm(column)
        current = re.search(r"(?:corrente|current)\s*(?:mppt|pv|entrada|input)\s*(\d+)", normalized)
        voltage = re.search(r"(?:tensao|voltage)\s*(?:mppt|pv|entrada|input)\s*(\d+)", normalized)
        if not current:
            current = re.search(r"(?:mppt|pv)\s*(\d+)\s*(?:corrente|current)", normalized)
        if not voltage:
            voltage = re.search(r"(?:mppt|pv)\s*(\d+)\s*(?:tensao|voltage)", normalized)
        if current:
            mapping[f"mppt_{int(current.group(1))}_current_a"] = column
        elif voltage:
            mapping[f"mppt_{int(voltage.group(1))}_voltage_v"] = column
        phase_voltage = re.search(r"(?:tensao|voltage)\s*(?:fase|phase)\s*([abc123])", normalized)
        phase_current = re.search(r"(?:corrente|current)\s*(?:fase|phase)\s*([abc123])", normalized)
        if phase_voltage:
            phase = {"1": "a", "2": "b", "3": "c"}.get(phase_voltage.group(1), phase_voltage.group(1))
            mapping[f"phase_{phase}_voltage_v"] = column
        elif phase_current:
            phase = {"1": "a", "2": "b", "3": "c"}.get(phase_current.group(1), phase_current.group(1))
            mapping[f"phase_{phase}_current_a"] = column
    phase_voltage_fields = [field for field in mapping if re.match(r"phase_[abc]_voltage_v", field)]
    if len(phase_voltage_fields) < 2:
        for field in phase_voltage_fields:
            mapping.pop(field, None)
    return mapping


def workbook_preview(content: bytes, sheet_name: str | None = None) -> tuple[list[str], pd.DataFrame, str]:
    try:
        workbook = pd.ExcelFile(BytesIO(content))
        selected = sheet_name if sheet_name in workbook.sheet_names else workbook.sheet_names[0]
        frame = pd.read_excel(workbook, sheet_name=selected)
    except Exception as exc:
        raise CurveAnalysisError("Não foi possível abrir o Excel. Confirme se o arquivo é .xlsx e não está protegido.") from exc
    if frame.empty or len(frame.columns) < 2:
        raise CurveAnalysisError("A planilha selecionada não contém uma tabela de telemetria utilizável.")
    return workbook.sheet_names, frame.head(12), selected


def _numeric(series: pd.Series) -> pd.Series:
    if series.dtype == object:
        text = series.astype(str).str.strip()
        comma_decimal = text.str.contains(",", regex=False)
        text.loc[comma_decimal] = text.loc[comma_decimal].str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        series = text
    return pd.to_numeric(series, errors="coerce")


def _analysis_date(filename: str, fallback: date | None) -> date:
    match = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", filename)
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            pass
    return fallback or date.today()


def _timestamps(series: pd.Series, day: date) -> pd.Series:
    def parse(value: object) -> pd.Timestamp | pd.NaT:
        if pd.isna(value):
            return pd.NaT
        if isinstance(value, datetime):
            return pd.Timestamp(value)
        if isinstance(value, time):
            return pd.Timestamp(datetime.combine(day, value))
        parsed = pd.to_datetime(str(value), errors="coerce", dayfirst=True)
        if pd.isna(parsed):
            return pd.NaT
        if parsed.year == datetime.now().year and not re.search(r"\d{4}", str(value)):
            return pd.Timestamp(datetime.combine(day, parsed.time()))
        return parsed

    return series.map(parse)


def _add_issue(issues: list[CurveIssue], severity: str, parameter: str, finding: str, cause: str, action: str) -> None:
    issues.append(CurveIssue(severity, parameter, finding, cause, action))


def analyze_inverter_curve(
    content: bytes,
    filename: str,
    *,
    sheet_name: str | None = None,
    column_mapping: dict[str, str] | None = None,
    analysis_day: date | None = None,
    nominal_power_kw: float = 0,
    nominal_grid_voltage_v: float = 220,
) -> dict[str, Any]:
    try:
        workbook = pd.ExcelFile(BytesIO(content))
        selected_sheet = sheet_name if sheet_name in workbook.sheet_names else workbook.sheet_names[0]
        raw = pd.read_excel(workbook, sheet_name=selected_sheet)
    except Exception as exc:
        raise CurveAnalysisError("Não foi possível ler o relatório. Use o arquivo .xlsx original exportado pelo portal.") from exc

    auto_mapping = suggest_column_mapping(list(raw.columns))
    mapping = {**auto_mapping, **(column_mapping or {})}
    mapping = {key: value for key, value in mapping.items() if value in raw.columns and value}
    if "timestamp" not in mapping:
        raise CurveAnalysisError("Não identifiquei a coluna de data/hora. Selecione-a no mapeamento manual.")
    if not ({"active_power_kw", "pv_power_kw"} & mapping.keys()):
        raise CurveAnalysisError("Não identifiquei uma coluna de potência ativa ou potência FV. Faça o mapeamento manual.")

    day = _analysis_date(filename, analysis_day)
    data = pd.DataFrame({"timestamp": _timestamps(raw[mapping["timestamp"]], day)})
    for field, column in mapping.items():
        if field != "timestamp":
            data[field] = _numeric(raw[column])
    data = data.dropna(subset=["timestamp"]).sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    numeric_columns = [column for column in data.columns if column != "timestamp"]
    data = data.dropna(how="all", subset=numeric_columns).reset_index(drop=True)
    if len(data) < 3:
        raise CurveAnalysisError("O relatório possui menos de três amostras válidas; não é possível avaliar a curva.")

    power_field = "active_power_kw" if "active_power_kw" in data else "pv_power_kw"
    power = data[power_field].fillna(0).clip(lower=0)
    peak = float(power.max())
    diffs = data["timestamp"].diff().dt.total_seconds().div(60).dropna()
    normal_diffs = diffs[(diffs > 0) & (diffs < 180)]
    interval_min = float(normal_diffs.median()) if not normal_diffs.empty else 0
    active_mask = power > max(peak * 0.02, 0.05)
    active_times = data.loc[active_mask, "timestamp"]
    operating_hours = float(active_mask.sum() * interval_min / 60) if interval_min else 0
    daily_energy = 0.0
    if "daily_energy_kwh" in data and data["daily_energy_kwh"].notna().any():
        counter = data["daily_energy_kwh"].dropna()
        daily_energy = float(counter.max() - min(float(counter.min()), 0.0))
        if daily_energy <= 0:
            daily_energy = float(counter.max())
    elif interval_min:
        daily_energy = float((power * interval_min / 60).sum())

    issues: list[CurveIssue] = []
    if interval_min and (diffs > max(interval_min * 2.5, interval_min + 10)).any():
        count = int((diffs > max(interval_min * 2.5, interval_min + 10)).sum())
        _add_issue(issues, "Atenção", "Qualidade dos dados", f"{count} intervalo(s) sem amostras acima do esperado.", "Falha de comunicação, portal ou datalogger.", "Conferir conectividade e comparar o período no portal do fabricante.")

    if peak > 0:
        useful = power > peak * 0.20
        neighbors_high = useful.shift(1, fill_value=False) & useful.shift(-1, fill_value=False)
        interruptions = (power <= peak * 0.01) & neighbors_high
        if interruptions.any():
            _add_issue(issues, "Crítica", "Curva de potência", f"{int(interruptions.sum())} interrupção(ões) abrupta(s) durante produção relevante.", "Desarme, reinício do inversor, falha de rede ou comunicação.", "Cruzar os horários com alarmes, tensão da rede e log do inversor.")

    if nominal_power_kw > 0:
        ratio = peak / nominal_power_kw
        if ratio < 0.50:
            _add_issue(issues, "Atenção", "Potência", f"Pico de {peak:.2f} kW ({ratio:.0%} da potência nominal informada).", "Irradiância baixa, sujeira, sombreamento, limitação ou indisponibilidade parcial.", "Comparar com clima/irradiância e com dias equivalentes antes de concluir perda.")
        clipped_minutes = int((power >= nominal_power_kw * 0.98).sum() * interval_min)
        if clipped_minutes >= 30:
            _add_issue(issues, "Observação", "Potência", f"Curva próxima da potência nominal por cerca de {clipped_minutes} min.", "Possível clipping, que pode ser normal conforme o dimensionamento DC/AC.", "Confirmar a razão DC/AC e o limite do modelo no datasheet.")

    if "frequency_hz" in data:
        frequency = data.loc[active_mask, "frequency_hz"].dropna()
        if not frequency.empty and ((frequency < 59.5) | (frequency > 60.5)).any():
            _add_issue(issues, "Atenção", "Rede elétrica", f"Frequência entre {frequency.min():.2f} e {frequency.max():.2f} Hz durante operação.", "Oscilação da rede, medição ou parametrização do inversor.", "Conferir limites do fabricante e registrar medição local com instrumento calibrado.")
    if "grid_voltage_v" in data and nominal_grid_voltage_v > 0:
        voltage = data.loc[active_mask, "grid_voltage_v"].dropna()
        if not voltage.empty and ((voltage < nominal_grid_voltage_v * 0.90) | (voltage > nominal_grid_voltage_v * 1.10)).any():
            _add_issue(issues, "Crítica", "Tensão da rede", f"Tensão entre {voltage.min():.1f} e {voltage.max():.1f} V fora de ±10% da referência.", "Queda/elevação de tensão, condutor inadequado ou rede da distribuidora.", "Verificar conexões e queda de tensão; confirmar critérios aplicáveis da concessionária.")
    for field, label, warning, critical in (
        ("heatsink_temp_c", "Temperatura do inversor", 65, 75),
        ("internal_temp_c", "Temperatura interna", 65, 75),
    ):
        if field in data and data[field].notna().any():
            maximum = float(data[field].max())
            if maximum >= warning:
                severity = "Crítica" if maximum >= critical else "Atenção"
                _add_issue(issues, severity, label, f"Máxima de {maximum:.1f} °C.", "Ventilação insuficiente, temperatura ambiente alta, sujeira ou sobrecarga.", "Limpar entradas de ar, conferir ventilação e o limite específico do datasheet.")
    if "insulation_kohm" in data and data["insulation_kohm"].notna().any():
        minimum = float(data.loc[data["insulation_kohm"] > 0, "insulation_kohm"].min()) if (data["insulation_kohm"] > 0).any() else 0
        if minimum and minimum < 1000:
            _add_issue(issues, "Crítica" if minimum < 200 else "Atenção", "Isolamento CC", f"Mínimo de {minimum:.0f} kΩ.", "Umidade, cabo/conector danificado ou fuga no arranjo FV.", "Inspecionar strings e medir isolamento conforme manual e procedimento de segurança.")
    if "leakage_ma" in data and data["leakage_ma"].notna().any():
        maximum = float(data["leakage_ma"].max())
        if maximum > 30:
            _add_issue(issues, "Crítica" if maximum > 100 else "Atenção", "Corrente de fuga", f"Máxima de {maximum:.1f} mA.", "Capacitância do arranjo, umidade ou falha de isolamento.", "Cruzar com alarmes RCMU e medir em campo antes de intervir.")

    mppt_ids = sorted({int(match.group(1)) for column in data.columns if (match := re.match(r"mppt_(\d+)_current_a", column))})
    mppt_summary = []
    for mppt_id in mppt_ids:
        current_col = f"mppt_{mppt_id}_current_a"
        voltage_col = f"mppt_{mppt_id}_voltage_v"
        current = data[current_col].fillna(0)
        voltage = data[voltage_col].fillna(0) if voltage_col in data else pd.Series(0.0, index=data.index)
        proxy_power = current * voltage / 1000
        mppt_summary.append({"mppt": f"MPPT {mppt_id}", "peak_current_a": float(current.max()), "peak_voltage_v": float(voltage.max()), "energy_proxy_kwh": float((proxy_power * interval_min / 60).sum()) if interval_min else 0})
    comparable = [item for item in mppt_summary if item["energy_proxy_kwh"] > 0]
    if len(comparable) >= 2:
        energies = [item["energy_proxy_kwh"] for item in comparable]
        imbalance = min(energies) / max(energies)
        if imbalance < 0.65:
            _add_issue(issues, "Atenção", "MPPTs", f"O menor MPPT entregou aproximadamente {imbalance:.0%} do maior.", "Strings diferentes, sombra, sujeira, falha/conector ou arranjos com quantidades distintas.", "Compare apenas MPPTs com módulos/orientação equivalentes e inspecione o arranjo de menor energia.")

    severity_order = {"Sem anomalias evidentes": 0, "Observação": 1, "Atenção": 2, "Crítica": 3}
    health_status = max((issue.severity for issue in issues), key=lambda value: severity_order.get(value, 0), default="Sem anomalias evidentes")
    summary = {
        "sheet": selected_sheet,
        "analysis_date": day.isoformat(),
        "sample_count": len(data),
        "interval_minutes": interval_min,
        "first_operation": active_times.min().isoformat() if not active_times.empty else None,
        "last_operation": active_times.max().isoformat() if not active_times.empty else None,
        "operating_hours": operating_hours,
        "peak_power_kw": peak,
        "daily_energy_kwh": daily_energy,
        "health_status": health_status,
        "issue_count": len(issues),
    }
    return {"data": data, "mapping": mapping, "summary": summary, "issues": issues, "mppt_summary": mppt_summary, "sheet_names": workbook.sheet_names}


def save_curve_analysis(plant_id: int, inverter_name: str, filename: str, result: dict[str, Any]) -> int:
    summary = result["summary"]
    issues = [asdict(issue) for issue in result["issues"]]
    return execute(
        """INSERT INTO inverter_curve_analyses
           (plant_id, analysis_date, inverter_name, source_filename, sample_count,
            daily_energy_kwh, peak_power_kw, health_status, issue_count, summary_json, issues_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (plant_id, summary["analysis_date"], inverter_name, filename, summary["sample_count"], summary["daily_energy_kwh"], summary["peak_power_kw"], summary["health_status"], summary["issue_count"], json.dumps(summary, ensure_ascii=False), json.dumps(issues, ensure_ascii=False)),
    )


def load_curve_history(plant_id: int) -> list[dict[str, Any]]:
    return query(
        """SELECT id, analysis_date, inverter_name, source_filename, sample_count,
                  daily_energy_kwh, peak_power_kw, health_status, issue_count, created_at
           FROM inverter_curve_analyses WHERE plant_id=? ORDER BY analysis_date DESC, id DESC""",
        (plant_id,),
    )
