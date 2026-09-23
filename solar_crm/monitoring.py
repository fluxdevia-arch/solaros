from __future__ import annotations

import base64
import calendar
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import format_datetime
from typing import Any
from urllib.parse import urlparse

import requests

from solar_crm.calculations import calculate_performance
from solar_crm.db import connect, execute, now_iso, query_one
from solar_crm.secure_store import protect_secret, unprotect_secret

GROWATT = "Growatt OpenAPI"
SOLIS = "SolisCloud"
SOLARZ = "SolarZ Monitoramento"
SUPPORTED_PROVIDERS = [SOLARZ, GROWATT, SOLIS]
DEFAULT_URLS = {
    SOLARZ: "https://app.solarz.com.br",
    GROWATT: "https://openapi.growatt.com",
    SOLIS: "https://www.soliscloud.com:13333",
}


class MonitoringError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class RemotePlant:
    remote_id: str
    name: str
    capacity_kwp: float = 0
    current_power_kw: float = 0
    total_energy_kwh: float = 0
    status: str = ""


@dataclass(frozen=True)
class DailyTelemetry:
    reading_date: str
    generation_kwh: float
    peak_power_kw: float = 0
    availability_pct: float | None = None
    alarms_count: int = 0
    expected_generation_kwh: float = 0


@dataclass(frozen=True)
class SyncResult:
    plant_id: int
    reference_month: str
    records_received: int
    generation_kwh: float
    performance_pct: float


@dataclass(frozen=True)
class ProviderProfile:
    portal_name: str
    credential_summary: str
    key_label: str
    secret_label: str
    key_placeholder: str
    secret_placeholder: str
    setup_steps: tuple[str, ...]
    documentation_url: str = ""


PROVIDER_PROFILES = {
    SOLARZ: ProviderProfile(
        portal_name="SolarZ Monitoramento",
        credential_summary="Usuário de API + senha de API",
        key_label="Usuário de API",
        secret_label="Senha da API",
        key_placeholder="Usuário gerado no menu Usuário de API",
        secret_placeholder="Senha exibida no momento da geração",
        setup_steps=(
            "Entre no SolarZ com a conta administradora.",
            "Acesse Configurações > Usuário de API > Gerar Usuário de API.",
            "Copie o usuário e a senha gerados. Não use o e-mail e a senha comuns do portal.",
        ),
        documentation_url="https://monitoramento.ajuda.solarz.com.br/monitoramento/api-solarz",
    ),
    GROWATT: ProviderProfile(
        portal_name="Growatt OpenAPI",
        credential_summary="API Token",
        key_label="",
        secret_label="API Token",
        key_placeholder="",
        secret_placeholder="Token gerado para acesso à OpenAPI",
        setup_steps=(
            "Entre no portal Growatt da conta instaladora.",
            "Solicite ou gere o token de acesso à OpenAPI para essa conta.",
            "Cole somente o token abaixo; o login e a senha comuns não funcionam neste conector.",
        ),
        documentation_url="https://openapi.growatt.com/",
    ),
    SOLIS: ProviderProfile(
        portal_name="SolisCloud",
        credential_summary="API ID + API Secret",
        key_label="API ID",
        secret_label="API Secret",
        key_placeholder="KeyID / API ID da SolisCloud",
        secret_placeholder="API Secret correspondente",
        setup_steps=(
            "Entre na SolisCloud com a conta proprietária ou instaladora.",
            "Ative o acesso de API e gere o par API ID / API Secret.",
            "Copie os dois valores exatamente como foram gerados; não use a senha comum do portal.",
        ),
    ),
}


def _validated_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise MonitoringError("A URL da API precisa ser HTTPS e possuir um domínio válido.")
    return value.strip().rstrip("/")


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _energy_kwh(value: Any, unit: Any = "kWh") -> float:
    amount = _float(value)
    normalized = str(unit or "kWh").strip().lower()
    if normalized == "mwh":
        return amount * 1000
    if normalized == "wh":
        return amount / 1000
    return amount


def _first_list(value: Any, preferred_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in preferred_keys:
        candidate = value.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        if isinstance(candidate, dict):
            nested = _first_list(candidate, preferred_keys)
            if nested:
                return nested
    for candidate in value.values():
        if isinstance(candidate, (dict, list)):
            nested = _first_list(candidate, preferred_keys)
            if nested:
                return nested
    return []


def _check_response(response: requests.Response, provider: str) -> Any:
    try:
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in {401, 403}:
            credential_help = {
                SOLARZ: "Gere um Usuário de API na SolarZ; o e-mail e a senha comuns do portal não funcionam.",
                GROWATT: "Confirme se o API Token está ativo e pertence à conta instaladora correta.",
                SOLIS: "Confirme o par API ID / API Secret e se o acesso de API está habilitado na SolisCloud.",
            }.get(provider, "Confira a credencial e a permissão da conta.")
            message = f"credencial recusada. {credential_help}"
        elif status_code == 400:
            message = "o portal recusou os parâmetros enviados. Confira se a credencial pertence ao portal selecionado e tente novamente."
        elif status_code == 404:
            message = f"rota da API não encontrada. Confirme o endereço do conector: {DEFAULT_URLS.get(provider, 'URL oficial do portal')}."
        else:
            message = f"falha HTTP ao acessar o portal ({exc})."
        raise MonitoringError(f"{provider}: {message}", status_code=status_code) from exc
    except ValueError as exc:
        raise MonitoringError(f"{provider}: o portal retornou uma resposta inválida.") from exc
    if not isinstance(payload, (dict, list)):
        raise MonitoringError(f"{provider}: resposta inesperada da API.")
    if isinstance(payload, list):
        return payload
    code = payload.get("error_code", payload.get("code", 0))
    if str(code) not in {"0", "", "None"}:
        message = payload.get("error_msg") or payload.get("msg") or f"código {code}"
        raise MonitoringError(f"{provider}: {message}")
    if payload.get("success") is False:
        raise MonitoringError(f"{provider}: {payload.get('msg') or 'operação recusada pelo portal'}")
    return payload


class SolarZClient:
    """Cliente da API oficial do integrador SolarZ."""

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str = DEFAULT_URLS[SOLARZ],
        session: requests.Session | None = None,
    ):
        if not username.strip() or not password.strip():
            raise MonitoringError("Informe o usuário de API e a senha da SolarZ.")
        self.username = username.strip()
        self.password = password.strip()
        self.base_url = _validated_base_url(base_url)
        self.session = session or requests.Session()

    def _post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        response = self.session.post(
            f"{self.base_url}{path}",
            json=data or {},
            params=query,
            auth=(self.username, self.password),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=25,
        )
        return _check_response(response, SOLARZ)

    def _list_all_plant_rows(self, path: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        # A API em produção da SolarZ rejeita page=0 e aceita page=1.
        page = 1
        while True:
            pagination = {"page": str(page), "pageSize": "20"}
            payload = self._post(path, pagination, query=pagination)
            page_rows = _first_list(payload, ("content", "plants", "list", "records"))
            rows.extend(page_rows)
            if not isinstance(payload, dict):
                break
            total_pages = int(_float(payload.get("totalPages")))
            if not page_rows or payload.get("last") is True or not total_pages or page >= total_pages:
                break
            page += 1
        return rows

    def list_plants(self) -> list[RemotePlant]:
        try:
            rows = self._list_all_plant_rows("/openApi/seller/plantWithInfos/list")
        except MonitoringError as exc:
            if exc.status_code not in {400, 404}:
                raise
            rows = []
        # Contas sem dados premium podem receber uma lista vazia na rota com
        # informações adicionais, mesmo possuindo usinas na listagem padrão.
        if not rows:
            rows = self._list_all_plant_rows("/openApi/seller/plant/list")
        plants: list[RemotePlant] = []
        for row in rows:
            if row.get("id") is None:
                continue
            status_value = row.get("status")
            if isinstance(status_value, dict):
                status_value = status_value.get("status") or ""
            plants.append(
                RemotePlant(
                    remote_id=str(row["id"]),
                    name=str(row.get("name") or "Usina SolarZ"),
                    capacity_kwp=_float(row.get("installedPower")),
                    total_energy_kwh=_float(row.get("energyProducedKwh")),
                    status=str(status_value or ""),
                )
            )
        return plants

    def fetch_month(self, remote_plant_id: str, reference_month: str) -> list[DailyTelemetry]:
        year_month = reference_month[:7]
        payload = self._post(
            f"/openApi/seller/plant/energy/plantId/{remote_plant_id}/month/{year_month}"
        )
        rows = _first_list(payload, ("content", "data", "records", "list"))
        return [
            DailyTelemetry(
                reading_date=str(row.get("date") or "")[:10],
                generation_kwh=_float(row.get("total")),
                expected_generation_kwh=_float(row.get("totalExpected")),
            )
            for row in rows
            if str(row.get("date") or "")[:7] == year_month
        ]


class GrowattClient:
    def __init__(self, token: str, base_url: str = DEFAULT_URLS[GROWATT], session: requests.Session | None = None):
        if not token.strip():
            raise MonitoringError("Informe o API Token da Growatt.")
        self.token = token.strip()
        self.base_url = _validated_base_url(base_url)
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers={"token": self.token, "Accept": "application/json"},
            timeout=25,
        )
        return _check_response(response, GROWATT)

    def list_plants(self) -> list[RemotePlant]:
        payload = self._get("/v1/plant/list", {"page": 1, "perpage": 100})
        rows = _first_list(payload.get("data", payload), ("plants", "plant_list", "list", "records", "datas"))
        return [
            RemotePlant(
                remote_id=str(row.get("plant_id") or row.get("id") or ""),
                name=str(row.get("name") or row.get("plant_name") or "Usina Growatt"),
                capacity_kwp=_float(row.get("peak_power") or row.get("nominal_power")),
                current_power_kw=_float(row.get("current_power")),
                total_energy_kwh=_energy_kwh(row.get("total_energy"), row.get("total_energy_unit", "kWh")),
                status=str(row.get("status") or ""),
            )
            for row in rows
            if row.get("plant_id") is not None or row.get("id") is not None
        ]

    def fetch_month(self, remote_plant_id: str, reference_month: str) -> list[DailyTelemetry]:
        year, month = (int(part) for part in reference_month[:7].split("-"))
        last_day = calendar.monthrange(year, month)[1]
        payload = self._get(
            "/v1/plant/energy",
            {
                "plant_id": remote_plant_id,
                "start_date": f"{year:04d}-{month:02d}-01",
                "end_date": f"{year:04d}-{month:02d}-{last_day:02d}",
                "time_unit": "day",
                "page": 1,
                "perpage": 100,
            },
        )
        rows = _first_list(payload.get("data", payload), ("energys", "energy", "records", "datas", "list"))
        return [
            DailyTelemetry(
                reading_date=str(row.get("date") or row.get("time") or "")[:10],
                generation_kwh=_energy_kwh(row.get("energy") or row.get("generation"), row.get("unit", "kWh")),
                peak_power_kw=_float(row.get("peak_power") or row.get("max_power")),
            )
            for row in rows
            if str(row.get("date") or row.get("time") or "")[:7] == f"{year:04d}-{month:02d}"
        ]


class SolisClient:
    content_type = "application/json;charset=UTF-8"

    def __init__(self, api_id: str, api_secret: str, base_url: str = DEFAULT_URLS[SOLIS], session: requests.Session | None = None):
        if not api_id.strip() or not api_secret.strip():
            raise MonitoringError("Informe o API ID e o API Secret da SolisCloud.")
        self.api_id = api_id.strip()
        self.api_secret = api_secret.strip()
        self.base_url = _validated_base_url(base_url)
        self.session = session or requests.Session()

    def _headers(self, path: str, body: bytes, request_time: datetime | None = None) -> dict[str, str]:
        digest = base64.b64encode(hashlib.md5(body).digest()).decode("ascii")
        moment = request_time or datetime.now(timezone.utc)
        date_header = format_datetime(moment.astimezone(timezone.utc), usegmt=True)
        canonical = f"POST\n{digest}\n{self.content_type}\n{date_header}\n{path}"
        signature = base64.b64encode(
            hmac.new(self.api_secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha1).digest()
        ).decode("ascii")
        return {
            "Content-MD5": digest,
            "Content-Type": self.content_type,
            "Date": date_header,
            "Authorization": f"API {self.api_id}:{signature}",
            "Accept": "application/json",
        }

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        response = self.session.post(
            f"{self.base_url}{path}",
            data=body,
            headers=self._headers(path, body),
            timeout=25,
        )
        return _check_response(response, SOLIS)

    def list_plants(self) -> list[RemotePlant]:
        payload = self._post("/v1/api/userStationList", {"pageNo": 1, "pageSize": 100})
        rows = _first_list(payload.get("data", {}), ("records", "page", "list", "stations"))
        return [
            RemotePlant(
                remote_id=str(row.get("id") or row.get("stationId") or row.get("nmiCode") or ""),
                name=str(row.get("stationName") or row.get("name") or "Usina SolisCloud"),
                capacity_kwp=_float(row.get("capacity") or row.get("power")),
                current_power_kw=_float(row.get("powerNow") or row.get("pac")),
                total_energy_kwh=_energy_kwh(row.get("allEnergy") or row.get("etotal"), row.get("allEnergyStr") or row.get("etotalStr") or "kWh"),
                status=str(row.get("state") or row.get("status") or ""),
            )
            for row in rows
            if row.get("id") is not None or row.get("stationId") is not None or row.get("nmiCode") is not None
        ]

    def fetch_month(self, remote_plant_id: str, reference_month: str) -> list[DailyTelemetry]:
        payload = self._post(
            "/v1/api/stationMonth",
            {"id": remote_plant_id, "money": "BRL", "month": reference_month[:7], "timeZone": -3},
        )
        rows = _first_list(payload.get("data", []), ("records", "list", "data"))
        return [
            DailyTelemetry(
                reading_date=str(row.get("dateStr") or "")[:10],
                generation_kwh=_energy_kwh(row.get("energy"), row.get("energyStr", "kWh")),
                peak_power_kw=_float(row.get("peakPower") or row.get("power")),
                alarms_count=int(_float(row.get("errorFlag"))),
            )
            for row in rows
            if str(row.get("dateStr") or "")[:7] == reference_month[:7]
        ]


def _connector(integration: dict[str, Any]):
    provider = integration["provider"]
    key = unprotect_secret(integration.get("credential_key_encrypted"))
    secret = unprotect_secret(integration.get("credential_secret_encrypted"))
    if provider == SOLARZ:
        return SolarZClient(key, secret, integration["base_url"])
    if provider == GROWATT:
        return GrowattClient(secret, integration["base_url"])
    if provider == SOLIS:
        return SolisClient(key, secret, integration["base_url"])
    raise MonitoringError(f"O provedor {provider} ainda não possui conector ativo.")


def validate_credentials(
    provider: str,
    base_url: str,
    credential_key: str,
    credential_secret: str,
) -> list[RemotePlant]:
    """Validate raw credentials without saving them and return visible plants."""
    if provider not in SUPPORTED_PROVIDERS:
        raise MonitoringError("Provedor de monitoramento não suportado.")
    url = _validated_base_url(base_url or DEFAULT_URLS[provider])
    if provider == SOLARZ:
        client = SolarZClient(credential_key, credential_secret, url)
    elif provider == GROWATT:
        client = GrowattClient(credential_secret, url)
    else:
        client = SolisClient(credential_key, credential_secret, url)
    return client.list_plants()


def _store_remote_plants(integration_id: int, plants: list[RemotePlant]) -> None:
    conn = connect()
    try:
        for plant in plants:
            conn.execute(
                """INSERT INTO remote_plants
                   (integration_id, remote_plant_id, name, capacity_kwp, current_power_kw,
                    total_energy_kwh, remote_status, discovered_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(integration_id, remote_plant_id) DO UPDATE SET
                     name=excluded.name, capacity_kwp=excluded.capacity_kwp,
                     current_power_kw=excluded.current_power_kw,
                     total_energy_kwh=excluded.total_energy_kwh,
                     remote_status=excluded.remote_status, discovered_at=excluded.discovered_at""",
                (
                    integration_id, plant.remote_id, plant.name, plant.capacity_kwp,
                    plant.current_power_kw, plant.total_energy_kwh, plant.status, now_iso(),
                ),
            )
        conn.execute(
            "UPDATE monitoring_integrations SET status='Conectada', last_error=NULL WHERE id=?",
            (integration_id,),
        )
        conn.commit()
    finally:
        conn.close()


def connect_and_discover(
    name: str,
    provider: str,
    base_url: str,
    credential_key: str,
    credential_secret: str,
    sync_interval_minutes: int = 60,
) -> tuple[int, list[RemotePlant]]:
    """Validate first, then securely save the account and imported plants."""
    if not name.strip():
        raise MonitoringError("Informe um nome para identificar esta conexão.")
    plants = validate_credentials(provider, base_url, credential_key, credential_secret)
    integration_id = create_integration(
        name,
        provider,
        base_url,
        credential_key,
        credential_secret,
        sync_interval_minutes,
    )
    _store_remote_plants(integration_id, plants)
    return integration_id, plants


def create_integration(name: str, provider: str, base_url: str, credential_key: str, credential_secret: str, sync_interval_minutes: int = 60) -> int:
    if provider not in SUPPORTED_PROVIDERS:
        raise MonitoringError("Provedor de monitoramento não suportado.")
    if not name.strip():
        raise MonitoringError("Informe um nome para a conexão.")
    url = _validated_base_url(base_url or DEFAULT_URLS[provider])
    if provider in {SOLARZ, SOLIS} and not credential_key.strip():
        provider_label = "usuário de API da SolarZ" if provider == SOLARZ else "API ID da SolisCloud"
        raise MonitoringError(f"Informe o {provider_label}.")
    if not credential_secret.strip():
        raise MonitoringError("Informe o token ou segredo da API.")
    hint_source = credential_key.strip() if provider in {SOLARZ, SOLIS} else credential_secret.strip()
    return execute(
        """INSERT INTO monitoring_integrations
           (name, provider, base_url, credential_key_encrypted, credential_secret_encrypted,
            credential_hint, status, sync_interval_minutes)
           VALUES (?, ?, ?, ?, ?, ?, 'Configurada', ?)""",
        (
            name.strip(),
            provider,
            url,
            protect_secret(credential_key.strip()),
            protect_secret(credential_secret.strip()),
            f"••••{hint_source[-4:]}" if hint_source else "-",
            max(15, int(sync_interval_minutes)),
        ),
    )


def update_integration_credentials(integration_id: int, credential_key: str, credential_secret: str) -> None:
    integration = query_one("SELECT * FROM monitoring_integrations WHERE id=?", (integration_id,))
    if not integration:
        raise MonitoringError("Conexão não encontrada.")
    key = credential_key.strip() or unprotect_secret(integration.get("credential_key_encrypted"))
    secret = credential_secret.strip() or unprotect_secret(integration.get("credential_secret_encrypted"))
    if integration["provider"] in {SOLARZ, SOLIS} and not key:
        provider_label = "usuário de API da SolarZ" if integration["provider"] == SOLARZ else "API ID da SolisCloud"
        raise MonitoringError(f"Informe o {provider_label}.")
    if not secret:
        raise MonitoringError("Informe o token ou segredo da API.")
    hint_source = key if integration["provider"] in {SOLARZ, SOLIS} else secret
    execute(
        """UPDATE monitoring_integrations
           SET credential_key_encrypted=?, credential_secret_encrypted=?, credential_hint=?,
               status='Configurada', last_error=NULL WHERE id=?""",
        (protect_secret(key), protect_secret(secret), f"••••{hint_source[-4:]}", integration_id),
    )


def discover_remote_plants(integration_id: int) -> list[RemotePlant]:
    integration = query_one("SELECT * FROM monitoring_integrations WHERE id=?", (integration_id,))
    if not integration:
        raise MonitoringError("Conexão não encontrada.")
    try:
        plants = _connector(integration).list_plants()
        _store_remote_plants(integration_id, plants)
        return plants
    except Exception as exc:
        execute(
            "UPDATE monitoring_integrations SET status='Erro', last_error=? WHERE id=?",
            (str(exc), integration_id),
        )
        if isinstance(exc, MonitoringError):
            raise
        raise MonitoringError(f"Não foi possível consultar o portal: {exc}") from exc


def link_plant(plant_id: int, integration_id: int, remote_plant_id: str, remote_device_sn: str = "") -> int:
    if not remote_plant_id.strip():
        raise MonitoringError("Selecione uma usina remota.")
    return execute(
        """INSERT INTO plant_integrations
           (plant_id, integration_id, remote_plant_id, remote_device_sn, status)
           VALUES (?, ?, ?, ?, 'Ativo')
           ON CONFLICT(plant_id) DO UPDATE SET integration_id=excluded.integration_id,
             remote_plant_id=excluded.remote_plant_id, remote_device_sn=excluded.remote_device_sn,
             status='Ativo', last_error=NULL""",
        (plant_id, integration_id, remote_plant_id.strip(), remote_device_sn.strip()),
    )


def import_remote_plant(integration_id: int, remote_plant_id: str, client_id: int) -> int:
    """Create a local CRM plant from a discovered portal plant and link it."""
    remote = query_one(
        """SELECT rp.*, mi.provider FROM remote_plants rp
           JOIN monitoring_integrations mi ON mi.id=rp.integration_id
           WHERE rp.integration_id=? AND rp.remote_plant_id=?""",
        (int(integration_id), remote_plant_id.strip()),
    )
    if not remote:
        raise MonitoringError("A usina importada não foi encontrada. Atualize a conexão e tente novamente.")
    existing = query_one(
        "SELECT plant_id FROM plant_integrations WHERE integration_id=? AND remote_plant_id=? AND status='Ativo'",
        (int(integration_id), remote_plant_id.strip()),
    )
    if existing:
        raise MonitoringError("Esta usina do portal já está vinculada ao GRID Engenharia.")
    client = query_one("SELECT id FROM clients WHERE id=? AND status='Ativo'", (int(client_id),))
    if not client:
        raise MonitoringError("Selecione um cliente ativo para receber a usina importada.")
    plant_id = execute(
        """INSERT INTO plants
           (client_id, name, installed_kwp, expected_monthly_kwh, status, notes)
           VALUES (?, ?, ?, 0, 'Operando', ?)""",
        (
            int(client_id),
            remote["name"],
            float(remote["capacity_kwp"] or 0),
            f"Importada automaticamente de {remote['provider']} · ID remoto {remote_plant_id}",
        ),
    )
    link_plant(plant_id, int(integration_id), remote_plant_id)
    return plant_id


def sync_mapping(mapping_id: int, reference_month: str) -> SyncResult:
    mapping = query_one(
        """SELECT pi.*, p.expected_monthly_kwh, mi.provider, mi.base_url,
                  mi.credential_key_encrypted, mi.credential_secret_encrypted
           FROM plant_integrations pi
           JOIN plants p ON p.id=pi.plant_id
           JOIN monitoring_integrations mi ON mi.id=pi.integration_id
           WHERE pi.id=? AND pi.status='Ativo'""",
        (mapping_id,),
    )
    if not mapping:
        raise MonitoringError("Vínculo de usina não encontrado ou inativo.")
    month = reference_month[:7] + "-01"
    started = now_iso()
    log_id = execute(
        """INSERT INTO integration_sync_logs
           (integration_id, plant_id, reference_month, started_at, status)
           VALUES (?, ?, ?, ?, 'Em andamento')""",
        (mapping["integration_id"], mapping["plant_id"], month, started),
    )
    try:
        rows = _connector(mapping).fetch_month(mapping["remote_plant_id"], month)
        valid_rows = [row for row in rows if row.reading_date[:7] == month[:7] and row.generation_kwh >= 0]
        generation = round(sum(row.generation_kwh for row in valid_rows), 3)
        portal_expected = round(sum(row.expected_generation_kwh for row in valid_rows), 3)
        expected = portal_expected if portal_expected > 0 else mapping["expected_monthly_kwh"]
        performance = calculate_performance(generation, expected)
        finished = now_iso()
        conn = connect()
        try:
            for row in valid_rows:
                conn.execute(
                    """INSERT INTO telemetry_daily
                       (plant_id, reading_date, generation_kwh, peak_power_kw, availability_pct,
                        alarms_count, source, synced_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(plant_id, reading_date, source) DO UPDATE SET
                         generation_kwh=excluded.generation_kwh,
                         peak_power_kw=excluded.peak_power_kw,
                         availability_pct=excluded.availability_pct,
                         alarms_count=excluded.alarms_count,
                         synced_at=excluded.synced_at""",
                    (
                        mapping["plant_id"], row.reading_date, row.generation_kwh,
                        row.peak_power_kw, row.availability_pct, row.alarms_count,
                        mapping["provider"], finished,
                    ),
                )
            conn.execute(
                """INSERT INTO readings
                   (plant_id, reference_month, generation_kwh, performance_ratio, meter_reading)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(plant_id, reference_month) DO UPDATE SET
                     generation_kwh=excluded.generation_kwh,
                     performance_ratio=excluded.performance_ratio,
                     meter_reading=excluded.meter_reading""",
                (
                    mapping["plant_id"], month, generation, performance,
                    f"Sincronização automática · {mapping['provider']} · {finished}",
                ),
            )
            conn.execute(
                """UPDATE plant_integrations SET last_sync_at=?, last_sync_status='Sucesso',
                   last_error=NULL WHERE id=?""",
                (finished, mapping_id),
            )
            conn.execute(
                """UPDATE monitoring_integrations SET last_sync_at=?, last_sync_status='Sucesso',
                   status='Conectada', last_error=NULL WHERE id=?""",
                (finished, mapping["integration_id"]),
            )
            conn.execute(
                """UPDATE integration_sync_logs SET finished_at=?, status='Sucesso',
                   records_received=?, generation_kwh=?, message=? WHERE id=?""",
                (finished, len(valid_rows), generation, "Leitura mensal atualizada.", log_id),
            )
            conn.commit()
        finally:
            conn.close()
        return SyncResult(mapping["plant_id"], month, len(valid_rows), generation, performance)
    except Exception as exc:
        finished = now_iso()
        message = str(exc)
        conn = connect()
        try:
            conn.execute(
                "UPDATE plant_integrations SET last_sync_at=?, last_sync_status='Erro', last_error=? WHERE id=?",
                (finished, message, mapping_id),
            )
            conn.execute(
                """UPDATE monitoring_integrations SET last_sync_at=?, last_sync_status='Erro',
                   status='Erro', last_error=? WHERE id=?""",
                (finished, message, mapping["integration_id"]),
            )
            conn.execute(
                """UPDATE integration_sync_logs SET finished_at=?, status='Erro', message=? WHERE id=?""",
                (finished, message, log_id),
            )
            conn.commit()
        finally:
            conn.close()
        if isinstance(exc, MonitoringError):
            raise
        raise MonitoringError(f"Falha na sincronização: {message}") from exc


def sync_all(reference_month: str) -> list[SyncResult]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id FROM plant_integrations WHERE status='Ativo' ORDER BY id"
        ).fetchall()
        mapping_ids = [row["id"] if isinstance(row, dict) else row[0] for row in rows]
    finally:
        conn.close()
    return [sync_mapping(mapping_id, reference_month) for mapping_id in mapping_ids]
