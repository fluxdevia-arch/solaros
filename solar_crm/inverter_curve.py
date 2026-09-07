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
    "serial_number": "Número de série",
    "timestamp": "Data/hora",
    "active_power_kw": "Potência ativa (kW)",
    "pv_power_kw": "Potência FV (kW)",
    "daily_energy_kwh": "Geração do dia (kWh)",
    "total_energy_mwh": "Geração total do inversor (MWh)",
    "grid_duration_h": "Tempo conectado à rede (h)",
    "frequency_hz": "Frequência da rede (Hz)",
    "grid_voltage_v": "Tensão da rede (V)",
    "heatsink_temp_c": "Temperatura do inversor/radiador (°C)",
    "internal_temp_c": "Temperatura interna (°C)",
    "insulation_kohm": "Resistência de isolamento (kΩ)",
    "leakage_ma": "Corrente de fuga (mA)",
    "power_factor": "Fator de potência",
    "reactive_power_kvar": "Potência reativa",
    "apparent_power_kva": "Potência aparente",
    "bus_voltage_v": "Tensão do barramento (V)",
    "fault_code": "Código de falha",
    "warning_code": "Código de aviso",
    "signal_dbm": "Sinal de comunicação",
}

ALIASES = {
    "serial_number": ("serial number", "numero de serie", "device serial", "inverter sn", "sn"),
    "timestamp": ("data hh mm", "data hora", "timestamp", "date time", "datetime", "time", "date", "horario", "hora"),
    "active_power_kw": ("potencia ativa", "active power", "pac", "ac output power", "output power"),
    "pv_power_kw": ("potencia pv total", "potencia fv total", "pv power", "dc input power", "input power"),
    "daily_energy_kwh": ("geracao hoje", "energia hoje", "daily yield", "today yield", "e today", "e day", "yield today"),
    "total_energy_mwh": ("geracao total", "energia total", "total yield", "e total", "lifetime yield"),
    "grid_duration_h": ("grid connection duration", "tempo conectado rede", "tempo conexao rede", "grid runtime"),
    "frequency_hz": ("frequencia da rede", "grid frequency", "ac side frequency", "ac frequency", "fac"),
    "grid_voltage_v": ("tensao fase a", "tensao da rede", "grid voltage", "ac voltage", "vac"),
    "heatsink_temp_c": ("temperatura radiador", "temperatura dissipador", "heatsink temperature", "inverter temperature"),
    "internal_temp_c": ("temperatura interna", "internal temperature", "ambient temperature"),
    "insulation_kohm": ("resistencia de isolamento", "insulation resistance", "riso"),
    "leakage_ma": ("corrente de fuga", "leakage current", "residual current"),
    "power_factor": ("fator de potencia", "power factor", "cos phi"),
    "reactive_power_kvar": ("potencia reativa", "reactive power", "qac"),
    "apparent_power_kva": ("potencia aparente", "apparent power", "sac"),
    "bus_voltage_v": ("tensao barramento", "bus voltage", "dc bus voltage"),
    "fault_code": ("fault code", "fault", "codigo falha", "falha"),
    "warning_code": ("warning code", "warning", "codigo aviso", "aviso"),
    "signal_dbm": ("signal value", "signal strength", "rssi", "sinal comunicacao"),
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
    alias_pattern = r"(?:^|\s)" + r"\s+".join(map(re.escape, alias.split())) + r"(?:\s|$)"
    if re.search(alias_pattern, normalized):
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
        if not current and not normalized.startswith("string"):
            current = re.search(r"(?:dc|input|entrada)\s*(?:corrente|current)\s*(\d+)", normalized)
        if not voltage and not normalized.startswith("string"):
            voltage = re.search(r"(?:dc|input|entrada)\s*(?:tensao|voltage)\s*(\d+)", normalized)
        if current:
            mapping[f"mppt_{int(current.group(1))}_current_a"] = column
        elif voltage:
            mapping[f"mppt_{int(voltage.group(1))}_voltage_v"] = column
        phase_voltage = re.search(r"(?:tensao|voltage)\s*(?:fase|phase)\s*([abcrst123])", normalized)
        phase_current = re.search(r"(?:corrente|current)\s*(?:fase|phase)\s*([abcrst123])", normalized)
        if not phase_voltage:
            phase_voltage = re.search(r"([abcrst123])\s*(?:fase|phase)\s*(?:tensao|voltage)", normalized)
        if not phase_current:
            phase_current = re.search(r"([abcrst123])\s*(?:fase|phase)\s*(?:corrente|current)", normalized)
        if phase_voltage:
            phase = {"1": "a", "2": "b", "3": "c", "r": "a", "s": "b", "t": "c"}.get(phase_voltage.group(1), phase_voltage.group(1))
            mapping[f"phase_{phase}_voltage_v"] = column
        elif phase_current:
            phase = {"1": "a", "2": "b", "3": "c", "r": "a", "s": "b", "t": "c"}.get(phase_current.group(1), phase_current.group(1))
            mapping[f"phase_{phase}_current_a"] = column
        line_voltage = re.search(r"(rs|rt|st|ab|ac|bc)\s*(?:line\s*)?(?:tensao|voltage)", normalized)
        if line_voltage:
            mapping[f"line_{line_voltage.group(1)}_voltage_v"] = column
        string_current = re.search(r"(?:string|str)\s*(?:corrente|current)?\s*(\d+)", normalized)
        if string_current and ("current" in normalized or "corrente" in normalized):
            mapping[f"string_{int(string_current.group(1))}_current_a"] = column
        string_voltage = re.search(r"(?:string|str)\s*(?:tensao|voltage)?\s*(\d+)", normalized)
        if string_voltage and ("voltage" in normalized or "tensao" in normalized):
            mapping[f"string_{int(string_voltage.group(1))}_voltage_v"] = column
        temperature = re.search(r"([uvw])\s*(?:phase\s*)?igbt\s*temperature", normalized)
        if temperature:
            mapping[f"igbt_{temperature.group(1)}_temp_c"] = column
        elif "boost temperature" in normalized or "temperatura boost" in normalized:
            mapping["boost_temp_c"] = column
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
    match = re.search(r"(?:^|[_-])(\d{2})[_-](\d{2})[_-](20\d{2})(?:\D|$)", filename)
    if match:
        try:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
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
        raw_value = str(value).strip()
        if re.match(r"^20\d{2}[-/]\d{1,2}[-/]\d{1,2}", raw_value):
            parsed = pd.to_datetime(raw_value, errors="coerce", yearfirst=True)
        else:
            parsed = pd.to_datetime(raw_value, errors="coerce", dayfirst=True)
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
    selected_day: date | None = None,
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
    serial_numbers: list[str] = []
    if "serial_number" in mapping:
        serial_numbers = [str(value) for value in raw[mapping["serial_number"]].dropna().unique() if str(value).strip()]
    data = pd.DataFrame({"timestamp": _timestamps(raw[mapping["timestamp"]], day)})
    for field, column in mapping.items():
        if field not in {"timestamp", "serial_number"}:
            data[field] = _numeric(raw[column])
    data = data.dropna(subset=["timestamp"]).sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    numeric_columns = [column for column in data.columns if column != "timestamp"]
    data = data.dropna(how="all", subset=numeric_columns).reset_index(drop=True)
    if len(data) < 3:
        raise CurveAnalysisError("O relatório possui menos de três amostras válidas; não é possível avaliar a curva.")

    available_days = sorted(data["timestamp"].dt.date.unique())
    if selected_day is not None:
        if selected_day not in available_days:
            raise CurveAnalysisError("A data escolhida não possui amostras neste arquivo.")
        data = data.loc[data["timestamp"].dt.date == selected_day].reset_index(drop=True)

    power_field = "active_power_kw" if "active_power_kw" in data else "pv_power_kw"
    power = data[power_field].fillna(0).clip(lower=0)
    peak = float(power.max())
    same_day = data["timestamp"].dt.date.eq(data["timestamp"].shift().dt.date)
    diffs = data["timestamp"].diff().dt.total_seconds().div(60)
    normal_diffs = diffs[same_day & (diffs > 0) & (diffs < 180)].dropna()
    interval_min = float(normal_diffs.median()) if not normal_diffs.empty else 0
    active_mask = power > max(peak * 0.02, 0.05)
    active_times = data.loc[active_mask, "timestamp"]
    daily_records: list[dict[str, Any]] = []
    for record_day, group in data.groupby(data["timestamp"].dt.date, sort=True):
        group_power = group[power_field].fillna(0).clip(lower=0)
        group_peak = float(group_power.max())
        group_active = group_power > max(group_peak * 0.02, 0.05)
        if "daily_energy_kwh" in group and group["daily_energy_kwh"].notna().any():
            day_energy = float(group["daily_energy_kwh"].max())
        else:
            day_energy = float((group_power * interval_min / 60).sum()) if interval_min else 0
        record = {
            "date": record_day,
            "energy_kwh": day_energy,
            "peak_power_kw": group_peak,
            "operating_hours": float(group_active.sum() * interval_min / 60) if interval_min else 0,
            "samples": len(group),
        }
        temperature_fields = [field for field in data if field.endswith("_temp_c")]
        temperature_values = pd.concat([group[field] for field in temperature_fields], ignore_index=True).dropna() if temperature_fields else pd.Series(dtype=float)
        record["max_temperature_c"] = float(temperature_values.max()) if not temperature_values.empty else None
        daily_records.append(record)
    daily_summary = pd.DataFrame(daily_records)
    period_energy = float(daily_summary["energy_kwh"].sum()) if not daily_summary.empty else 0
    operating_hours = float(daily_summary["operating_hours"].sum()) if not daily_summary.empty else 0
    total_counter_delta_kwh = 0.0
    if "total_energy_mwh" in data and data["total_energy_mwh"].notna().any():
        lifetime = data["total_energy_mwh"].dropna()
        total_counter_delta_kwh = max(float(lifetime.max() - lifetime.min()) * 1000, 0)

    issues: list[CurveIssue] = []
    gap_limit = max(interval_min * 2.5, interval_min + 10)
    active_before = active_mask.shift(fill_value=False)
    meaningful_gaps = same_day & (diffs > gap_limit) & active_before & active_mask if interval_min else pd.Series(False, index=data.index)
    if meaningful_gaps.any():
        count = int(meaningful_gaps.sum())
        _add_issue(issues, "Atenção", "Qualidade dos dados", f"{count} intervalo(s) sem amostras acima do esperado.", "Falha de comunicação, portal ou datalogger.", "Conferir conectividade e comparar o período no portal do fabricante.")

    if peak > 0:
        useful = power > peak * 0.20
        same_as_previous = data["timestamp"].dt.date.eq(data["timestamp"].shift().dt.date)
        same_as_next = data["timestamp"].dt.date.eq(data["timestamp"].shift(-1).dt.date)
        neighbors_high = useful.shift(1, fill_value=False) & useful.shift(-1, fill_value=False) & same_as_previous & same_as_next
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
    phase_voltage_fields = [field for field in data if field == "grid_voltage_v" or re.match(r"phase_[abc]_voltage_v", field)]
    if phase_voltage_fields and nominal_grid_voltage_v > 0:
        voltage = pd.concat([data.loc[active_mask, field] for field in phase_voltage_fields], ignore_index=True).dropna()
        if not voltage.empty and ((voltage < nominal_grid_voltage_v * 0.90) | (voltage > nominal_grid_voltage_v * 1.10)).any():
            _add_issue(issues, "Crítica", "Tensão da rede", f"Tensão entre {voltage.min():.1f} e {voltage.max():.1f} V fora de ±10% da referência.", "Queda/elevação de tensão, condutor inadequado ou rede da distribuidora.", "Verificar conexões e queda de tensão; confirmar critérios aplicáveis da concessionária.")
    phase_current_fields = [field for field in data if re.match(r"phase_[abc]_current_a", field)]
    if len(phase_current_fields) >= 2:
        phase_currents = data.loc[active_mask, phase_current_fields].apply(pd.to_numeric, errors="coerce")
        row_mean = phase_currents.mean(axis=1).replace(0, pd.NA)
        imbalance = ((phase_currents.max(axis=1) - phase_currents.min(axis=1)) / row_mean).dropna()
        if not imbalance.empty and float(imbalance.median()) > 0.10:
            _add_issue(issues, "Atenção", "Correntes CA", f"Desequilíbrio mediano entre fases de {float(imbalance.median()):.0%}.", "Carga/rede desequilibrada, medição ou anomalia na saída do inversor.", "Comparar as três fases em carga e conferir conexões e parâmetros do inversor.")
    temperature_checks = [
        (field, "Temperatura interna" if field == "internal_temp_c" else "Temperatura do inversor", 65, 75)
        for field in data if field.endswith("_temp_c")
    ]
    checked_temperature_labels: set[str] = set()
    for field, label, warning, critical in temperature_checks:
        if field in data and data[field].notna().any():
            maximum = float(data[field].max())
            if maximum >= warning and label not in checked_temperature_labels:
                severity = "Crítica" if maximum >= critical else "Atenção"
                _add_issue(issues, severity, label, f"Máxima de {maximum:.1f} °C.", "Ventilação insuficiente, temperatura ambiente alta, sujeira ou sobrecarga.", "Limpar entradas de ar, conferir ventilação e o limite específico do datasheet.")
                checked_temperature_labels.add(label)
    if "insulation_kohm" in data and data["insulation_kohm"].notna().any():
        minimum = float(data.loc[data["insulation_kohm"] > 0, "insulation_kohm"].min()) if (data["insulation_kohm"] > 0).any() else 0
        if minimum and minimum < 1000:
            _add_issue(issues, "Crítica" if minimum < 200 else "Atenção", "Isolamento CC", f"Mínimo de {minimum:.0f} kΩ.", "Umidade, cabo/conector danificado ou fuga no arranjo FV.", "Inspecionar strings e medir isolamento conforme manual e procedimento de segurança.")
    if "leakage_ma" in data and data["leakage_ma"].notna().any():
        maximum = float(data["leakage_ma"].max())
        if maximum > 30:
            _add_issue(issues, "Crítica" if maximum > 100 else "Atenção", "Corrente de fuga", f"Máxima de {maximum:.1f} mA.", "Capacitância do arranjo, umidade ou falha de isolamento.", "Cruzar com alarmes RCMU e medir em campo antes de intervir.")
    for field, label in (("fault_code", "Falhas registradas"), ("warning_code", "Avisos registrados")):
        if field in data:
            events = data.loc[data[field].fillna(0) != 0, field]
            if not events.empty:
                codes = ", ".join(map(lambda value: f"{value:g}", sorted(events.unique())[:8]))
                _add_issue(issues, "Crítica" if field == "fault_code" else "Atenção", label, f"{len(events)} amostra(s) com código diferente de zero: {codes}.", "Evento reportado pelo firmware do inversor.", "Consultar a descrição dos códigos no manual do modelo e cruzar com data e horário.")

    mppt_ids = sorted({int(match.group(1)) for column in data.columns if (match := re.match(r"mppt_(\d+)_current_a", column))})
    mppt_summary = []
    for mppt_id in mppt_ids:
        current_col = f"mppt_{mppt_id}_current_a"
        voltage_col = f"mppt_{mppt_id}_voltage_v"
        current = data[current_col].fillna(0)
        voltage = data[voltage_col].fillna(0) if voltage_col in data else pd.Series(0.0, index=data.index)
        proxy_power = current * voltage / 1000
        if (current > 0).any() or (voltage > 0).any():
            mppt_summary.append({"mppt": f"MPPT {mppt_id}", "peak_current_a": float(current.max()), "peak_voltage_v": float(voltage.max()), "energy_proxy_kwh": float((proxy_power * interval_min / 60).sum()) if interval_min else 0})
    comparable = [item for item in mppt_summary if item["energy_proxy_kwh"] > 0]
    if len(comparable) >= 2:
        energies = [item["energy_proxy_kwh"] for item in comparable]
        imbalance = min(energies) / max(energies)
        if imbalance < 0.65:
            _add_issue(issues, "Atenção", "MPPTs", f"O menor MPPT entregou aproximadamente {imbalance:.0%} do maior.", "Strings diferentes, sombra, sujeira, falha/conector ou arranjos com quantidades distintas.", "Compare apenas MPPTs com módulos/orientação equivalentes e inspecione o arranjo de menor energia.")

    recognized_string_fields = sorted(field for field in data if re.match(r"string_\d+_current_a", field))
    string_summary: list[dict[str, Any]] = []
    for field in recognized_string_fields:
        values = data[field].dropna()
        nonzero = values[values > 0]
        if not nonzero.empty:
            string_summary.append({
                "string": f"String {int(field.split('_')[1])}",
                "peak_current_a": float(nonzero.max()),
                "mean_current_a": float(nonzero.mean()),
                "samples": int(nonzero.count()),
            })
    if len(string_summary) >= 2:
        current_means = [item["mean_current_a"] for item in string_summary]
        string_ratio = min(current_means) / max(current_means) if max(current_means) else 1
        if string_ratio < 0.65:
            _add_issue(issues, "Atenção", "Strings", f"A string de menor corrente média entregou {string_ratio:.0%} da maior.", "Sombreamento, sujeira, conector/cabo, fusível ou diferença de módulos.", "Comparar somente strings equivalentes e medir corrente individualmente em condição uniforme.")
    elif recognized_string_fields and not string_summary:
        _add_issue(
            issues,
            "Observação",
            "Dados por string",
            f"O arquivo possui {len(recognized_string_fields)} coluna(s) de string, mas todas vieram sem valores.",
            "O modelo, datalogger ou perfil do portal não disponibilizou telemetria individual das strings neste arquivo.",
            "Verificar no portal se existe outro relatório com corrente por string; os dois canais CC/MPPT disponíveis continuam analisados.",
        )

    severity_order = {"Sem anomalias evidentes": 0, "Observação": 1, "Atenção": 2, "Crítica": 3}
    health_status = max((issue.severity for issue in issues), key=lambda value: severity_order.get(value, 0), default="Sem anomalias evidentes")
    date_start = min(data["timestamp"].dt.date)
    date_end = max(data["timestamp"].dt.date)
    day_count = int(data["timestamp"].dt.date.nunique())
    best_day = daily_summary.loc[daily_summary["energy_kwh"].idxmax()] if not daily_summary.empty else None
    summary = {
        "sheet": selected_sheet,
        "analysis_date": (selected_day or date_end).isoformat(),
        "analysis_type": "Diária" if day_count == 1 else "Período",
        "date_start": date_start.isoformat(),
        "date_end": date_end.isoformat(),
        "day_count": day_count,
        "sample_count": len(data),
        "interval_minutes": interval_min,
        "first_operation": active_times.min().isoformat() if not active_times.empty else None,
        "last_operation": active_times.max().isoformat() if not active_times.empty else None,
        "operating_hours": operating_hours,
        "peak_power_kw": peak,
        "daily_energy_kwh": period_energy,
        "period_energy_kwh": period_energy,
        "average_daily_energy_kwh": float(daily_summary["energy_kwh"].mean()) if not daily_summary.empty else 0,
        "best_day": best_day["date"].isoformat() if best_day is not None else None,
        "best_day_energy_kwh": float(best_day["energy_kwh"]) if best_day is not None else 0,
        "total_counter_delta_kwh": total_counter_delta_kwh,
        "serial_numbers": serial_numbers,
        "health_status": health_status,
        "issue_count": len(issues),
    }
    mapped_sources = set(mapping.values())
    coverage = {
        "source_column_count": len(raw.columns),
        "mapped_column_count": len(mapped_sources),
        "unmapped_columns": [str(column) for column in raw.columns if str(column) not in mapped_sources],
        "recognized_string_channels": len(recognized_string_fields),
        "string_channels_with_values": len(string_summary),
        "recognized_mppts": len(mppt_ids),
        "mppts_with_values": len(mppt_summary),
    }
    return {
        "data": data,
        "mapping": mapping,
        "summary": summary,
        "issues": issues,
        "mppt_summary": mppt_summary,
        "string_summary": string_summary,
        "daily_summary": daily_summary,
        "coverage": coverage,
        "available_days": available_days,
        "sheet_names": workbook.sheet_names,
    }


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
