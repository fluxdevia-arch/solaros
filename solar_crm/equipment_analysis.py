from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

from solar_crm.db import connect, execute, now_iso, query, query_one
from solar_crm.secure_store import protect_secret, unprotect_secret


NORMALIZED_REST = "REST normalizada"
EQUIPMENT_PROVIDERS = [
    NORMALIZED_REST,
    "Huawei FusionSolar",
    "Growatt OpenAPI",
    "SolisCloud",
    "Deye Cloud",
    "Sungrow iSolarCloud",
]
AUTH_TYPES = ["Bearer token", "Basic Auth", "API key no cabeçalho", "Sem autenticação"]


class EquipmentAnalysisError(RuntimeError):
    pass


@dataclass(frozen=True)
class StringDiagnostic:
    integration_id: int
    source_name: str
    inverter_name: str
    mppt: str
    string_name: str
    status: str
    score: float
    current_a: float
    voltage_v: float
    current_ratio: float
    loss_kwh: float
    energy_kwh: float
    peer_energy_kwh: float
    pattern: str
    probable_cause: str
    confidence: float
    sample_count: int


@dataclass(frozen=True)
class EquipmentSyncResult:
    string_samples: int
    alarms: int


def _validated_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise EquipmentAnalysisError("A URL da API precisa usar HTTPS e possuir um domínio válido.")
    return value.strip().rstrip("/")


def _validated_path(value: str, label: str) -> str:
    path = value.strip()
    if not path.startswith("/") or "://" in path:
        raise EquipmentAnalysisError(f"{label} deve ser um caminho relativo iniciado por /.")
    return path


def create_equipment_integration(
    *,
    plant_id: int,
    name: str,
    provider: str,
    base_url: str,
    auth_type: str,
    credential_key: str,
    credential_secret: str,
    device_sn: str,
    strings_path: str,
    alarms_path: str,
) -> int:
    if provider not in EQUIPMENT_PROVIDERS:
        raise EquipmentAnalysisError("Fabricante ou adaptador não suportado.")
    if not name.strip():
        raise EquipmentAnalysisError("Informe um nome para a fonte de dados.")
    if auth_type not in AUTH_TYPES:
        raise EquipmentAnalysisError("Selecione uma autenticação válida.")
    if auth_type != "Sem autenticação" and not credential_secret.strip():
        raise EquipmentAnalysisError("Informe o token, senha ou segredo da API.")
    url = _validated_base_url(base_url)
    string_endpoint = _validated_path(strings_path, "O endpoint de strings")
    alarm_endpoint = _validated_path(alarms_path, "O endpoint de alarmes")
    hint_source = credential_key.strip() or credential_secret.strip()
    return execute(
        """INSERT INTO equipment_integrations
           (plant_id, name, provider, base_url, auth_type, credential_key_encrypted,
            credential_secret_encrypted, credential_hint, device_sn, strings_path,
            alarms_path, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Configurada')""",
        (
            int(plant_id),
            name.strip(),
            provider,
            url,
            auth_type,
            protect_secret(credential_key.strip()),
            protect_secret(credential_secret.strip()),
            f"••••{hint_source[-4:]}" if hint_source else "-",
            device_sn.strip(),
            string_endpoint,
            alarm_endpoint,
        ),
    )


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "content", "records", "list", "items", "result"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
        if isinstance(candidate, dict):
            nested = _extract_rows(candidate)
            if nested:
                return nested
    return []


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _request_headers(source: dict[str, Any]) -> tuple[dict[str, str], tuple[str, str] | None]:
    key = unprotect_secret(source.get("credential_key_encrypted"))
    secret = unprotect_secret(source.get("credential_secret_encrypted"))
    headers = {"Accept": "application/json"}
    auth = None
    if source["auth_type"] == "Bearer token":
        headers["Authorization"] = f"Bearer {secret}"
    elif source["auth_type"] == "Basic Auth":
        auth = (key, secret)
    elif source["auth_type"] == "API key no cabeçalho":
        headers[key or "X-API-Key"] = secret
    return headers, auth


def _endpoint(source: dict[str, Any], path_key: str, reading_day: date) -> str:
    try:
        path = str(source[path_key]).format(
            device_sn=source.get("device_sn") or "",
            date=reading_day.isoformat(),
        )
    except (KeyError, ValueError) as exc:
        raise EquipmentAnalysisError(f"O caminho {path_key} contém um marcador inválido.") from exc
    return f"{source['base_url']}{path}"


def sync_equipment_integration(
    integration_id: int,
    reading_day: date,
    *,
    session: requests.Session | None = None,
) -> EquipmentSyncResult:
    source = query_one("SELECT * FROM equipment_integrations WHERE id=?", (int(integration_id),))
    if not source:
        raise EquipmentAnalysisError("Fonte de equipamentos não encontrada.")
    if source["provider"] != NORMALIZED_REST:
        raise EquipmentAnalysisError(
            "Este fabricante exige um adaptador próprio. Use REST normalizada por meio do gateway do "
            "fabricante ou solicite a ativação do conector específico."
        )
    client = session or requests.Session()
    headers, auth = _request_headers(source)
    try:
        strings_response = client.get(
            _endpoint(source, "strings_path", reading_day),
            headers=headers,
            auth=auth,
            timeout=30,
        )
        strings_response.raise_for_status()
        string_rows = _extract_rows(strings_response.json())
        alarms_response = client.get(
            _endpoint(source, "alarms_path", reading_day),
            headers=headers,
            auth=auth,
            timeout=30,
        )
        alarms_response.raise_for_status()
        alarm_rows = _extract_rows(alarms_response.json())
    except requests.RequestException as exc:
        execute(
            "UPDATE equipment_integrations SET status='Erro', last_sync_status='Erro', last_error=? WHERE id=?",
            (str(exc), int(integration_id)),
        )
        raise EquipmentAnalysisError(f"A API do equipamento recusou a consulta: {exc}") from exc
    except ValueError as exc:
        raise EquipmentAnalysisError("A API do equipamento não retornou JSON válido.") from exc

    normalized_samples = []
    for row in string_rows:
        timestamp = str(row.get("timestamp") or row.get("sample_at") or row.get("datetime") or "")
        string_name = str(row.get("string") or row.get("string_name") or row.get("input") or "")
        if not timestamp or not string_name:
            continue
        normalized_samples.append(
            (
                int(integration_id),
                timestamp,
                str(row.get("inverter") or row.get("inverter_name") or source["name"]),
                str(row.get("mppt") or row.get("tracker") or "MPPT 1"),
                string_name,
                _float(row.get("current_a") if row.get("current_a") is not None else row.get("current")),
                _float(row.get("voltage_v") if row.get("voltage_v") is not None else row.get("voltage")),
                _float(row.get("power_kw") if row.get("power_kw") is not None else row.get("power")),
                "API",
            )
        )

    normalized_alarms = []
    for index, row in enumerate(alarm_rows):
        occurred_at = str(row.get("timestamp") or row.get("occurred_at") or row.get("datetime") or now_iso())
        external_id = str(row.get("id") or row.get("code") or f"{occurred_at}-{index}")
        normalized_alarms.append(
            (
                int(integration_id),
                external_id,
                occurred_at,
                str(row.get("code") or "-")[:80],
                str(row.get("severity") or row.get("level") or "Atenção")[:30],
                str(row.get("title") or row.get("name") or "Alarme do inversor")[:180],
                str(row.get("message") or row.get("description") or "")[:2000],
                str(row.get("status") or "Aberto")[:30],
            )
        )

    synced_at = now_iso()
    conn = connect()
    try:
        conn.executemany(
            """INSERT INTO equipment_string_samples
               (integration_id, sample_at, inverter_name, mppt, string_name, current_a,
                voltage_v, power_kw, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(integration_id, sample_at, inverter_name, mppt, string_name)
               DO UPDATE SET current_a=excluded.current_a, voltage_v=excluded.voltage_v,
                             power_kw=excluded.power_kw, source=excluded.source""",
            normalized_samples,
        )
        conn.executemany(
            """INSERT INTO equipment_alarms
               (integration_id, external_id, occurred_at, code, severity, title, message, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(integration_id, external_id)
               DO UPDATE SET occurred_at=excluded.occurred_at, severity=excluded.severity,
                             title=excluded.title, message=excluded.message, status=excluded.status""",
            normalized_alarms,
        )
        conn.execute(
            """UPDATE equipment_integrations SET status='Conectada', last_sync_at=?,
               last_sync_status='Sucesso', last_error=NULL WHERE id=?""",
            (synced_at, int(integration_id)),
        )
        conn.commit()
    finally:
        conn.close()
    return EquipmentSyncResult(len(normalized_samples), len(normalized_alarms))


def _hours_between(first: str, second: str) -> float:
    try:
        start = datetime.fromisoformat(first.replace("Z", "+00:00"))
        end = datetime.fromisoformat(second.replace("Z", "+00:00"))
        return min(max((end - start).total_seconds() / 3600, 0), 2)
    except ValueError:
        return 0


def analyze_string_samples(rows: Iterable[dict[str, Any]]) -> list[StringDiagnostic]:
    samples = [dict(row) for row in rows]
    if not samples:
        return []
    peer_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in samples:
        key = (str(row["sample_at"]), str(row["inverter_name"]), str(row["mppt"]))
        peer_groups.setdefault(key, []).append(row)
    peers: dict[tuple[str, str, str], tuple[float, float]] = {}
    for key, group in peer_groups.items():
        currents = [_float(candidate["current_a"]) for candidate in group if _float(candidate["current_a"]) > 0.15]
        powers = [_float(candidate["power_kw"]) for candidate in group if _float(candidate["power_kw"]) > 0.01]
        peers[key] = (median(currents) if currents else 0, median(powers) if powers else 0)

    grouped: dict[tuple[int, str, str, str, str], list[dict[str, Any]]] = {}
    for row in samples:
        key = (
            int(row["integration_id"]),
            str(row.get("source_name") or "Fonte de equipamentos"),
            str(row["inverter_name"]),
            str(row["mppt"]),
            str(row["string_name"]),
        )
        grouped.setdefault(key, []).append(row)

    diagnostics: list[StringDiagnostic] = []
    for key, group in grouped.items():
        ordered = sorted(group, key=lambda item: str(item["sample_at"]))
        ratios: list[float] = []
        deficit_hours: list[int] = []
        energy = 0.0
        peer_energy = 0.0
        loss = 0.0
        for index, row in enumerate(ordered):
            peer_current, peer_power = peers[(str(row["sample_at"]), str(row["inverter_name"]), str(row["mppt"]))]
            current = _float(row["current_a"])
            if peer_current > 0.5:
                ratio = current / peer_current
                ratios.append(ratio)
                if ratio < 0.88:
                    try:
                        deficit_hours.append(datetime.fromisoformat(str(row["sample_at"])).hour)
                    except ValueError:
                        pass
            interval = _hours_between(str(row["sample_at"]), str(ordered[index + 1]["sample_at"])) if index + 1 < len(ordered) else 0
            power = _float(row["power_kw"])
            energy += power * interval
            peer_energy += peer_power * interval
            loss += max(peer_power - power, 0) * interval
        current_ratio = median(ratios) if ratios else 0
        low_share = sum(1 for ratio in ratios if ratio < 0.88) / len(ratios) if ratios else 0
        unique_hours = sorted(set(deficit_hours))
        longest_window = 0
        run = 0
        previous = None
        for hour in unique_hours:
            run = run + 1 if previous is not None and hour == previous + 1 else 1
            longest_window = max(longest_window, run)
            previous = hour
        if current_ratio < 0.5:
            status, score = "Crítica", max(5.0, current_ratio * 100)
        elif current_ratio < 0.78:
            status, score = "Degradada", current_ratio * 100
        elif current_ratio < 0.90:
            status, score = "Atenção", current_ratio * 100
        else:
            status, score = "Saudável", min(current_ratio * 100, 100)

        if status == "Saudável":
            pattern, cause, confidence = "normal", "Sem anomalia relevante", 0.96
        elif low_share >= 0.70:
            pattern, cause, confidence = "constante", "Conexão elétrica, fusível ou string aberta", 0.91
        elif longest_window >= 3:
            pattern, cause, confidence = "janela", "Sombreamento ou sujeira localizada", 0.86
        else:
            pattern, cause, confidence = "intermitente", "Conector, cabeamento ou comunicação instável", 0.79
        latest = ordered[-1]
        diagnostics.append(
            StringDiagnostic(
                integration_id=key[0],
                source_name=key[1],
                inverter_name=key[2],
                mppt=key[3],
                string_name=key[4],
                status=status,
                score=round(score, 1),
                current_a=_float(latest["current_a"]),
                voltage_v=_float(latest["voltage_v"]),
                current_ratio=round(current_ratio, 3),
                loss_kwh=round(loss, 2),
                energy_kwh=round(energy, 2),
                peer_energy_kwh=round(peer_energy, 2),
                pattern=pattern,
                probable_cause=cause,
                confidence=confidence,
                sample_count=len(ordered),
            )
        )
    order = {"Crítica": 0, "Degradada": 1, "Atenção": 2, "Saudável": 3}
    return sorted(diagnostics, key=lambda item: (order[item.status], item.inverter_name, item.mppt, item.string_name))


def load_string_samples(plant_id: int, reading_day: date) -> list[dict[str, Any]]:
    start = reading_day.isoformat()
    end = (reading_day + timedelta(days=1)).isoformat()
    return query(
        """SELECT ess.*, ei.name AS source_name, ei.provider
           FROM equipment_string_samples ess
           JOIN equipment_integrations ei ON ei.id=ess.integration_id
           WHERE ei.plant_id=? AND ess.sample_at>=? AND ess.sample_at<?
           ORDER BY ess.sample_at, ess.inverter_name, ess.mppt, ess.string_name""",
        (int(plant_id), start, end),
    )


def load_equipment_alarms(plant_id: int, *, only_open: bool = False) -> list[dict[str, Any]]:
    clause = "AND ea.status NOT IN ('Resolvido', 'Fechado')" if only_open else ""
    return query(
        f"""SELECT ea.occurred_at, ea.code, ea.severity, ea.title, ea.message, ea.status,
                   ei.name AS source_name, ei.provider
            FROM equipment_alarms ea
            JOIN equipment_integrations ei ON ei.id=ea.integration_id
            WHERE ei.plant_id=? {clause}
            ORDER BY ea.occurred_at DESC""",
        (int(plant_id),),
    )


def available_equipment_days(plant_id: int) -> list[date]:
    rows = query(
        """SELECT DISTINCT substr(ess.sample_at, 1, 10) AS reading_day
           FROM equipment_string_samples ess
           JOIN equipment_integrations ei ON ei.id=ess.integration_id
           WHERE ei.plant_id=? ORDER BY reading_day DESC""",
        (int(plant_id),),
    )
    return [date.fromisoformat(row["reading_day"]) for row in rows if row.get("reading_day")]
