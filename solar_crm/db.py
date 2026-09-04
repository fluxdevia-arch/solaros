from __future__ import annotations

import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from solar_crm.config import database_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_db_path() -> Path:
    custom = os.getenv("SOLAR_CRM_DB")
    path = Path(custom) if custom else PROJECT_ROOT / "data" / "solar_crm.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def using_postgres() -> bool:
    return bool(database_url())


def _postgres_sql(sql: str) -> str:
    """Translate the small SQLite-compatible SQL subset used by SolarOS."""
    translated = re.sub(
        r"date\(\s*\?\s*,\s*'\+1 year'\s*\)",
        "(CAST(%s AS DATE) + INTERVAL '1 year')::date",
        sql,
        flags=re.IGNORECASE,
    )
    translated = re.sub(r"date\(\s*'now'\s*\)", "CURRENT_DATE", translated, flags=re.IGNORECASE)
    translated = re.sub(r"date\(\s*\?\s*\)", "CAST(%s AS DATE)", translated, flags=re.IGNORECASE)
    return translated.replace("?", "%s")


def _postgres_schema() -> str:
    schema = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    schema = re.sub(r"\bREAL\b", "DOUBLE PRECISION", schema)
    schema = re.sub(r"\bBLOB\b", "BYTEA", schema)
    schema = schema.replace("DEFAULT CURRENT_TIMESTAMP", "DEFAULT (CURRENT_TIMESTAMP::TEXT)")
    return schema


class PostgresConnection:
    """Compatibility wrapper that keeps the app's parameterized SQLite SQL portable."""

    is_postgres = True

    def __init__(self, url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - exercised only in hosted mode
            raise RuntimeError("Instale 'psycopg[binary]' para usar o PostgreSQL.") from exc
        self._connection = psycopg.connect(url, row_factory=dict_row)

    def execute(self, sql: str, params: Iterable[Any] = ()):
        return self._connection.execute(_postgres_sql(sql), tuple(params))

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]):
        return self._connection.cursor().executemany(
            _postgres_sql(sql), [tuple(row) for row in rows]
        )

    def executescript(self, script: str) -> None:
        for statement in _postgres_schema().split(";"):
            if statement.strip():
                self._connection.execute(statement)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def connect() -> sqlite3.Connection | PostgresConnection:
    url = database_url()
    if url:
        return PostgresConnection(url)
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    company_name TEXT NOT NULL,
    legal_name TEXT,
    document TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    report_footer TEXT,
    technical_name TEXT,
    technical_title TEXT,
    technical_registration TEXT,
    signature_image BLOB,
    signature_image_mime TEXT,
    share_base_url TEXT DEFAULT 'http://localhost:8501'
);

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    document TEXT,
    client_type TEXT NOT NULL DEFAULT 'Pessoa jurídica',
    contact_name TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    status TEXT NOT NULL DEFAULT 'Ativo',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    unit_code TEXT,
    distributor TEXT,
    address TEXT,
    connection_type TEXT,
    installed_kwp REAL NOT NULL DEFAULT 0,
    expected_monthly_kwh REAL NOT NULL DEFAULT 0,
    commissioning_date TEXT,
    inverter TEXT,
    modules TEXT,
    monitoring_url TEXT,
    status TEXT NOT NULL DEFAULT 'Operando',
    warranty_expiry TEXT,
    next_cleaning_date TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    plan TEXT NOT NULL,
    start_date TEXT NOT NULL,
    billing_day INTEGER NOT NULL DEFAULT 10,
    base_fee REAL NOT NULL DEFAULT 0,
    per_plant_fee REAL NOT NULL DEFAULT 0,
    per_kwp_fee REAL NOT NULL DEFAULT 0,
    extras_fee REAL NOT NULL DEFAULT 0,
    discount_pct REAL NOT NULL DEFAULT 0,
    billing_cycle TEXT NOT NULL DEFAULT 'Mensal',
    status TEXT NOT NULL DEFAULT 'Ativo',
    scope TEXT,
    reajust_index TEXT DEFAULT 'IPCA',
    next_reajust_date TEXT
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    reference_month TEXT NOT NULL,
    consumption_kwh REAL NOT NULL DEFAULT 0,
    generation_kwh REAL NOT NULL DEFAULT 0,
    injected_kwh REAL NOT NULL DEFAULT 0,
    compensated_kwh REAL NOT NULL DEFAULT 0,
    tariff REAL NOT NULL DEFAULT 0,
    billed_amount REAL NOT NULL DEFAULT 0,
    reference_amount REAL NOT NULL DEFAULT 0,
    availability_pct REAL NOT NULL DEFAULT 100,
    performance_ratio REAL NOT NULL DEFAULT 0,
    downtime_hours REAL NOT NULL DEFAULT 0,
    incidents INTEGER NOT NULL DEFAULT 0,
    failure_notes TEXT,
    meter_reading TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(plant_id, reference_month)
);

CREATE TABLE IF NOT EXISTS beneficiaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    unit_code TEXT NOT NULL,
    holder_name TEXT,
    allocation_pct REAL NOT NULL DEFAULT 0 CHECK(allocation_pct >= 0 AND allocation_pct <= 100),
    status TEXT NOT NULL DEFAULT 'Ativo',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(plant_id, unit_code)
);

CREATE TABLE IF NOT EXISTS beneficiary_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    beneficiary_id INTEGER NOT NULL REFERENCES beneficiaries(id) ON DELETE CASCADE,
    reference_month TEXT NOT NULL,
    allocated_kwh REAL NOT NULL DEFAULT 0,
    compensated_kwh REAL NOT NULL DEFAULT 0,
    billed_consumption_kwh REAL NOT NULL DEFAULT 0,
    previous_credit_kwh REAL NOT NULL DEFAULT 0,
    ending_credit_kwh REAL NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(beneficiary_id, reference_month)
);

CREATE TABLE IF NOT EXISTS monitoring_integrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL,
    credential_key_encrypted TEXT,
    credential_secret_encrypted TEXT NOT NULL,
    credential_hint TEXT,
    status TEXT NOT NULL DEFAULT 'Configurada',
    sync_interval_minutes INTEGER NOT NULL DEFAULT 60,
    last_sync_at TEXT,
    last_sync_status TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS remote_plants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    integration_id INTEGER NOT NULL REFERENCES monitoring_integrations(id) ON DELETE CASCADE,
    remote_plant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    capacity_kwp REAL NOT NULL DEFAULT 0,
    current_power_kw REAL NOT NULL DEFAULT 0,
    total_energy_kwh REAL NOT NULL DEFAULT 0,
    remote_status TEXT,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(integration_id, remote_plant_id)
);

CREATE TABLE IF NOT EXISTS plant_integrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    integration_id INTEGER NOT NULL REFERENCES monitoring_integrations(id) ON DELETE CASCADE,
    remote_plant_id TEXT NOT NULL,
    remote_device_sn TEXT,
    status TEXT NOT NULL DEFAULT 'Ativo',
    last_sync_at TEXT,
    last_sync_status TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(plant_id),
    UNIQUE(integration_id, remote_plant_id)
);

CREATE TABLE IF NOT EXISTS telemetry_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    reading_date TEXT NOT NULL,
    generation_kwh REAL NOT NULL DEFAULT 0,
    peak_power_kw REAL NOT NULL DEFAULT 0,
    availability_pct REAL,
    alarms_count INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(plant_id, reading_date, source)
);

CREATE TABLE IF NOT EXISTS integration_sync_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    integration_id INTEGER NOT NULL REFERENCES monitoring_integrations(id) ON DELETE CASCADE,
    plant_id INTEGER REFERENCES plants(id) ON DELETE SET NULL,
    reference_month TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    records_received INTEGER NOT NULL DEFAULT 0,
    generation_kwh REAL NOT NULL DEFAULT 0,
    message TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    plant_id INTEGER REFERENCES plants(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'Média',
    due_date TEXT NOT NULL,
    recurrence TEXT NOT NULL DEFAULT 'Única',
    status TEXT NOT NULL DEFAULT 'Pendente',
    assignee TEXT,
    notes TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    plant_id INTEGER REFERENCES plants(id) ON DELETE SET NULL,
    opened_at TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'Média',
    status TEXT NOT NULL DEFAULT 'Aberto',
    sla_hours INTEGER NOT NULL DEFAULT 24,
    resolved_at TEXT,
    root_cause TEXT,
    resolution TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    reference_month TEXT NOT NULL,
    due_date TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Pendente',
    paid_at TEXT,
    notes TEXT,
    UNIQUE(contract_id, reference_month)
);

CREATE TABLE IF NOT EXISTS cash_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_type TEXT NOT NULL CHECK (transaction_type IN ('Receita','Despesa')),
    category TEXT NOT NULL,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    plant_id INTEGER REFERENCES plants(id) ON DELETE SET NULL,
    competence_month TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    settlement_date TEXT,
    amount REAL NOT NULL CHECK (amount >= 0),
    status TEXT NOT NULL,
    payment_method TEXT,
    document_number TEXT,
    description TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    lead_name TEXT NOT NULL,
    company TEXT,
    contact_name TEXT,
    phone TEXT,
    email TEXT,
    service_type TEXT NOT NULL,
    source TEXT,
    stage TEXT NOT NULL DEFAULT 'Lead recebido',
    estimated_value REAL NOT NULL DEFAULT 0,
    probability_pct REAL NOT NULL DEFAULT 20,
    expected_close_date TEXT,
    next_action TEXT,
    next_action_date TEXT,
    owner TEXT,
    notes TEXT,
    lost_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS service_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT UNIQUE,
    public_token TEXT NOT NULL UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    plant_id INTEGER REFERENCES plants(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    service_type TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'Média',
    status TEXT NOT NULL DEFAULT 'Aberta',
    requested_at TEXT NOT NULL,
    scheduled_date TEXT,
    assignee TEXT,
    address TEXT NOT NULL,
    contact_name TEXT,
    contact_phone TEXT,
    work_description TEXT NOT NULL,
    safety_instructions TEXT,
    materials TEXT,
    completion_notes TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS site_inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT UNIQUE,
    public_token TEXT NOT NULL UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    plant_id INTEGER REFERENCES plants(id) ON DELETE SET NULL,
    service_order_id INTEGER REFERENCES service_orders(id) ON DELETE SET NULL,
    inspection_type TEXT NOT NULL DEFAULT 'Vistoria técnica',
    status TEXT NOT NULL DEFAULT 'Rascunho',
    urgency TEXT NOT NULL DEFAULT 'Rotina',
    inspected_at TEXT NOT NULL,
    technician TEXT,
    contact_name TEXT,
    contact_phone TEXT,
    address TEXT NOT NULL,
    weather TEXT,
    ambient_temperature_c REAL,
    roof_type TEXT,
    roof_condition TEXT,
    access_condition TEXT,
    latitude REAL,
    longitude REAL,
    solar_orientation TEXT,
    azimuth_deg REAL,
    tilt_deg REAL,
    shading_level TEXT,
    shading_sources TEXT,
    dc_voltage_v REAL,
    dc_current_a REAL,
    ac_voltage_v REAL,
    ac_current_a REAL,
    insulation_mohm REAL,
    grounding_ohm REAL,
    generation_power_kw REAL,
    inverter_alarms TEXT,
    safety_risks TEXT,
    findings TEXT,
    actions_performed TEXT,
    recommendations TEXT,
    materials_needed TEXT,
    follow_up_date TEXT,
    client_acknowledgement TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inspection_checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id INTEGER NOT NULL REFERENCES site_inspections(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    item TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Não verificado',
    notes TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(inspection_id, item)
);

CREATE TABLE IF NOT EXISTS inspection_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id INTEGER NOT NULL REFERENCES site_inspections(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    caption TEXT,
    filename TEXT,
    mime_type TEXT NOT NULL,
    image_data BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS service_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    contract_type TEXT NOT NULL,
    title TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    duration_months INTEGER NOT NULL DEFAULT 12,
    amount REAL NOT NULL DEFAULT 0,
    billing_cycle TEXT NOT NULL DEFAULT 'Mensal',
    payment_terms TEXT,
    scope TEXT NOT NULL,
    contractor_obligations TEXT,
    client_obligations TEXT,
    termination_terms TEXT,
    additional_terms TEXT,
    venue TEXT,
    status TEXT NOT NULL DEFAULT 'Rascunho',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pv_modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer TEXT,
    model TEXT NOT NULL,
    power_wp REAL NOT NULL,
    voc_v REAL NOT NULL,
    vmp_v REAL NOT NULL,
    isc_a REAL NOT NULL,
    imp_a REAL NOT NULL,
    temp_coeff_voc_pct REAL NOT NULL DEFAULT -0.25,
    temp_coeff_pmax_pct REAL NOT NULL DEFAULT -0.35,
    max_series_fuse_a REAL NOT NULL DEFAULT 25,
    width_mm REAL NOT NULL DEFAULT 1134,
    height_mm REAL NOT NULL DEFAULT 2278,
    datasheet_name TEXT,
    datasheet_mime TEXT,
    datasheet_data BLOB,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(manufacturer, model)
);

CREATE TABLE IF NOT EXISTS pv_inverters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer TEXT,
    model TEXT NOT NULL,
    nominal_power_kw REAL NOT NULL,
    max_dc_power_kw REAL NOT NULL,
    max_dc_voltage_v REAL NOT NULL,
    mppt_min_v REAL NOT NULL,
    mppt_max_v REAL NOT NULL,
    mppt_count INTEGER NOT NULL DEFAULT 1,
    strings_per_mppt INTEGER NOT NULL DEFAULT 1,
    max_input_current_mppt_a REAL NOT NULL,
    max_short_circuit_current_mppt_a REAL NOT NULL,
    ac_voltage_v REAL NOT NULL DEFAULT 230,
    phases TEXT NOT NULL DEFAULT 'Monofásico',
    efficiency_pct REAL NOT NULL DEFAULT 98,
    datasheet_name TEXT,
    datasheet_mime TEXT,
    datasheet_data BLOB,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(manufacturer, model)
);

CREATE TABLE IF NOT EXISTS sizing_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT UNIQUE,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    address TEXT,
    module_id INTEGER NOT NULL REFERENCES pv_modules(id),
    inverter_id INTEGER NOT NULL REFERENCES pv_inverters(id),
    module_count INTEGER NOT NULL,
    modules_per_string INTEGER NOT NULL,
    layout_rows INTEGER NOT NULL,
    layout_columns INTEGER NOT NULL,
    module_orientation TEXT NOT NULL DEFAULT 'Retrato',
    roof_type TEXT,
    roof_azimuth_deg REAL NOT NULL DEFAULT 0,
    roof_tilt_deg REAL NOT NULL DEFAULT 0,
    minimum_temperature_c REAL NOT NULL DEFAULT 12,
    maximum_cell_temperature_c REAL NOT NULL DEFAULT 70,
    dc_cable_length_m REAL NOT NULL DEFAULT 20,
    ac_cable_length_m REAL NOT NULL DEFAULT 15,
    voltage_drop_limit_pct REAL NOT NULL DEFAULT 1.5,
    correction_factor REAL NOT NULL DEFAULT 0.8,
    has_external_spda INTEGER NOT NULL DEFAULT 0,
    roof_image_name TEXT,
    roof_image_mime TEXT,
    roof_image_data BLOB,
    result_json TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'Rascunho',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    service_type TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    payment_terms TEXT,
    scope TEXT NOT NULL,
    deliverables TEXT,
    exclusions TEXT,
    deadline_days INTEGER NOT NULL DEFAULT 15,
    status TEXT NOT NULL DEFAULT 'Rascunho',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_plants_client ON plants(client_id);
CREATE INDEX IF NOT EXISTS idx_readings_month ON readings(reference_month);
CREATE INDEX IF NOT EXISTS idx_beneficiaries_plant ON beneficiaries(plant_id, status);
CREATE INDEX IF NOT EXISTS idx_beneficiary_readings_month ON beneficiary_readings(reference_month);
CREATE INDEX IF NOT EXISTS idx_remote_plants_integration ON remote_plants(integration_id);
CREATE INDEX IF NOT EXISTS idx_plant_integrations_integration ON plant_integrations(integration_id, status);
CREATE INDEX IF NOT EXISTS idx_telemetry_daily_plant_date ON telemetry_daily(plant_id, reading_date);
CREATE INDEX IF NOT EXISTS idx_integration_sync_logs_started ON integration_sync_logs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_date, status);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_cash_competence ON cash_transactions(competence_month, transaction_type, status);
CREATE INDEX IF NOT EXISTS idx_cash_due ON cash_transactions(due_date, status);
CREATE INDEX IF NOT EXISTS idx_opportunities_stage ON opportunities(stage, next_action_date);
CREATE INDEX IF NOT EXISTS idx_service_orders_status ON service_orders(status, scheduled_date);
CREATE INDEX IF NOT EXISTS idx_service_orders_token ON service_orders(public_token);
CREATE INDEX IF NOT EXISTS idx_site_inspections_status ON site_inspections(status, inspected_at);
CREATE INDEX IF NOT EXISTS idx_site_inspections_token ON site_inspections(public_token);
CREATE INDEX IF NOT EXISTS idx_inspection_items_inspection ON inspection_checklist_items(inspection_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_inspection_photos_inspection ON inspection_photos(inspection_id, created_at);
CREATE INDEX IF NOT EXISTS idx_service_contracts_client ON service_contracts(client_id, status);
CREATE INDEX IF NOT EXISTS idx_sizing_projects_client ON sizing_projects(client_id, status);
CREATE INDEX IF NOT EXISTS idx_proposals_client ON proposals(client_id, status);
CREATE INDEX IF NOT EXISTS idx_proposals_opportunity ON proposals(opportunity_id);
"""


def init_db(seed: bool = True) -> None:
    conn = connect()
    try:
        if getattr(conn, "is_postgres", False):
            # Streamlit can start more than one session while a deployment is warming up.
            # Serialize DDL so concurrent CREATE TABLE IF NOT EXISTS statements do not
            # race while PostgreSQL creates their implicit composite types.
            conn.execute("SELECT pg_advisory_xact_lock(1397705807)")
        conn.executescript(SCHEMA)
        _ensure_schema_columns(conn)
        count_row = conn.execute("SELECT COUNT(*) AS value FROM settings").fetchone()
        count = count_row["value"] if isinstance(count_row, dict) else count_row[0]
        fresh_install = count == 0
        if count == 0:
            conn.execute(
                """INSERT INTO settings
                   (id, company_name, legal_name, document, email, phone, address, report_footer,
                    technical_name, technical_title, technical_registration,
                    signature_image, signature_image_mime)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "SolarOS Energia Solar",
                    "SolarOS Energia Solar Ltda.",
                    "00.000.000/0001-00",
                    "relacionamento@solaros.com.br",
                    "(00) 00000-0000",
                    "Sua cidade - UF",
                    "Este relatório consolida dados de monitoramento e fatura informados no sistema.",
                    "Carlos Jessé Soares",
                    "Téc. Eletrotécnica",
                    "CFT: 11551320410",
                    None,
                    None,
                ),
            )
        conn.execute(
            """UPDATE settings
               SET company_name='SolarOS Energia Solar',
                   legal_name='SolarOS Energia Solar Ltda.',
                   email=CASE WHEN email='relacionamento@solare.com.br' THEN 'relacionamento@solaros.com.br' ELSE email END
               WHERE company_name='Solare Gestão de Energia'
                 AND legal_name='Solare Serviços de Energia Ltda.'"""
        )
        conn.execute(
            """UPDATE settings
               SET technical_name=COALESCE(NULLIF(technical_name,''), 'Carlos Jessé Soares'),
                   technical_title=COALESCE(NULLIF(technical_title,''), 'Téc. Eletrotécnica'),
                   technical_registration=COALESCE(NULLIF(technical_registration,''), 'CFT: 11551320410')
               WHERE id=1"""
        )
        if seed and fresh_install:
            _seed(conn)
        conn.commit()
    finally:
        conn.close()


def _ensure_schema_columns(conn: sqlite3.Connection | PostgresConnection) -> None:
    if getattr(conn, "is_postgres", False):
        additions = {
            "technical_name": "TEXT",
            "technical_title": "TEXT",
            "technical_registration": "TEXT",
            "signature_image": "BYTEA",
            "signature_image_mime": "TEXT",
            "share_base_url": "TEXT DEFAULT 'http://localhost:8501'",
        }
        for name, column_type in additions.items():
            conn.execute(f"ALTER TABLE settings ADD COLUMN IF NOT EXISTS {name} {column_type}")
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    additions = {
        "technical_name": "TEXT",
        "technical_title": "TEXT",
        "technical_registration": "TEXT",
        "signature_image": "BLOB",
        "signature_image_mime": "TEXT",
        "share_base_url": "TEXT DEFAULT 'http://localhost:8501'",
    }
    for name, column_type in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE settings ADD COLUMN {name} {column_type}")


def _seed(conn: sqlite3.Connection | PostgresConnection) -> None:
    clients = [
        ("Mercado Bom Dia", "12.345.678/0001-10", "Pessoa jurídica", "Marina Costa", "marina@mercadobomdia.com.br", "(62) 99911-2200", "Av. Central, 450", "Goiânia", "GO", "Ativo", "Cliente prioritário. Enviar relatório até o 5º dia útil."),
        ("Fazenda Santa Clara", "987.654.321-00", "Pessoa física", "Carlos Nogueira", "carlos@fazendasantaclara.com.br", "(64) 98822-3300", "Rodovia GO-210, km 12", "Rio Verde", "GO", "Ativo", "Acesso à usina mediante agendamento."),
        ("Clínica Horizonte", "23.456.789/0001-20", "Pessoa jurídica", "Dra. Aline Ramos", "financeiro@clinicahorizonte.com.br", "(11) 97733-4400", "Rua das Palmeiras, 88", "Campinas", "SP", "Ativo", "Contrato inclui reunião trimestral de resultados."),
    ]
    conn.executemany(
        """INSERT INTO clients
        (name, document, client_type, contact_name, email, phone, address, city, state, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        clients,
    )

    plants = [
        (1, "Loja Matriz", "UC-10023871", "Equatorial GO", "Av. Central, 450 - Goiânia/GO", "Trifásica", 74.8, 10100, "2024-02-15", "2x Growatt MID 36KTL3-X", "136x 550 Wp", "https://exemplo.monitoramento/loja-matriz", "Operando", "2034-02-15", _iso_days(18), "Limpeza preferencialmente aos domingos."),
        (1, "Centro de Distribuição", "UC-10023899", "Equatorial GO", "Distrito Industrial - Aparecida de Goiânia/GO", "Trifásica", 112.2, 14900, "2024-05-20", "2x Sungrow SG50CX", "204x 550 Wp", "https://exemplo.monitoramento/cd", "Atenção", "2034-05-20", _iso_days(-4), "String 7 com oscilação intermitente."),
        (2, "Usina Fazenda", "UC-99100231", "Equatorial GO", "Rodovia GO-210, km 12 - Rio Verde/GO", "Trifásica", 48.4, 6800, "2023-09-04", "Huawei SUN2000-50KTL", "88x 550 Wp", "https://exemplo.monitoramento/fazenda", "Operando", "2033-09-04", _iso_days(42), "Monitorar sombreamento no período de chuvas."),
        (3, "Clínica - Bloco A", "UC-88771102", "CPFL Paulista", "Rua das Palmeiras, 88 - Campinas/SP", "Trifásica", 39.6, 5100, "2025-01-18", "Solis 40K-5G", "72x 550 Wp", "https://exemplo.monitoramento/clinica", "Operando", "2035-01-18", _iso_days(28), "Gerador de emergência no mesmo quadro; registrar intervenções."),
    ]
    conn.executemany(
        """INSERT INTO plants
        (client_id, name, unit_code, distributor, address, connection_type, installed_kwp,
         expected_monthly_kwh, commissioning_date, inverter, modules, monitoring_url,
         status, warranty_expiry, next_cleaning_date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        plants,
    )

    contracts = [
        (1, "Performance", "2024-02-15", 10, 390, 140, 1.8, 180, 5, "Mensal", "Ativo", "Monitoramento diário, relatório mensal, gestão de faturas e 2 visitas preventivas/ano.", "IPCA", "2027-02-15"),
        (2, "Essencial", "2023-09-04", 8, 250, 90, 1.2, 0, 0, "Mensal", "Ativo", "Monitoramento semanal, relatório mensal e suporte remoto.", "IPCA", "2026-09-04"),
        (3, "Premium", "2025-01-18", 5, 520, 180, 2.0, 260, 0, "Mensal", "Ativo", "Monitoramento diário, relatórios, reunião trimestral e manutenção preventiva.", "IPCA", "2027-01-18"),
    ]
    conn.executemany(
        """INSERT INTO contracts
        (client_id, plan, start_date, billing_day, base_fee, per_plant_fee, per_kwp_fee,
         extras_fee, discount_pct, billing_cycle, status, scope, reajust_index, next_reajust_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        contracts,
    )

    month_starts = _recent_months(6)
    plant_specs = {
        1: (10100, 9700, 0.96),
        2: (14900, 15600, 0.91),
        3: (6800, 6200, 1.02),
        4: (5100, 5500, 0.98),
    }
    factors = [0.88, 0.94, 1.03, 1.07, 0.97, 1.01]
    for plant_id, (expected, consumption, baseline_pr) in plant_specs.items():
        for idx, month in enumerate(month_starts):
            generation = round(expected * factors[idx] * (0.82 if plant_id == 2 and idx == 4 else 1), 1)
            consumed = round(consumption * (0.96 + idx * 0.012), 1)
            tariff = 0.91 + idx * 0.012
            reference = round(consumed * tariff + 140, 2)
            billed = round(max(consumed - generation * 0.88, 180) * tariff + 125, 2)
            incidents = 1 if plant_id == 2 and idx == 4 else 0
            failure = "Baixa geração na string 7; inspeção agendada." if incidents else ""
            conn.execute(
                """INSERT INTO readings
                (plant_id, reference_month, consumption_kwh, generation_kwh, injected_kwh,
                 compensated_kwh, tariff, billed_amount, reference_amount, availability_pct,
                 performance_ratio, downtime_hours, incidents, failure_notes, meter_reading)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plant_id,
                    month,
                    consumed,
                    generation,
                    round(generation * 0.72, 1),
                    round(min(generation * 0.82, consumed), 1),
                    tariff,
                    billed,
                    reference,
                    97.2 if incidents else 99.7,
                    round((generation / expected) * 100 * baseline_pr, 1),
                    8.5 if incidents else 0.6,
                    incidents,
                    failure,
                    f"Leitura validada em {month[5:7]}/{month[:4]}",
                ),
            )

    beneficiaries = [
        (1, "Filial Setor Oeste", "UC-BEN-1001", "Mercado Bom Dia Ltda.", 60, "Ativo", "Rateio prioritário da matriz."),
        (1, "Depósito Norte", "UC-BEN-1002", "Mercado Bom Dia Ltda.", 40, "Ativo", "Unidade beneficiária secundária."),
        (2, "Loja Aparecida", "UC-BEN-2001", "Mercado Bom Dia Ltda.", 50, "Ativo", ""),
        (2, "Centro Administrativo", "UC-BEN-2002", "Mercado Bom Dia Ltda.", 30, "Ativo", ""),
        (2, "Loja Sul", "UC-BEN-2003", "Mercado Bom Dia Ltda.", 20, "Ativo", ""),
        (3, "Sede da fazenda", "UC-BEN-3001", "Carlos Nogueira", 70, "Ativo", ""),
        (3, "Sistema de irrigação", "UC-BEN-3002", "Carlos Nogueira", 30, "Ativo", ""),
        (4, "Clínica - Bloco A", "UC-BEN-4001", "Clínica Horizonte Ltda.", 65, "Ativo", "Autoconsumo remoto."),
        (4, "Clínica - Bloco B", "UC-BEN-4002", "Clínica Horizonte Ltda.", 35, "Ativo", ""),
    ]
    conn.executemany(
        """INSERT INTO beneficiaries
        (plant_id, name, unit_code, holder_name, allocation_pct, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        beneficiaries,
    )
    beneficiary_rows = conn.execute(
        "SELECT id, plant_id, allocation_pct FROM beneficiaries ORDER BY id"
    ).fetchall()
    for beneficiary in beneficiary_rows:
        allocation_factor = float(beneficiary["allocation_pct"]) / 100
        plant_readings = conn.execute(
            "SELECT reference_month, generation_kwh, compensated_kwh FROM readings WHERE plant_id=?",
            (beneficiary["plant_id"],),
        ).fetchall()
        for reading in plant_readings:
            allocated = round(float(reading["generation_kwh"]) * allocation_factor, 1)
            compensated = round(float(reading["compensated_kwh"]) * allocation_factor, 1)
            previous_credit = round(allocated * 0.08, 1)
            ending_credit = round(previous_credit + allocated - compensated, 1)
            conn.execute(
                """INSERT INTO beneficiary_readings
                (beneficiary_id, reference_month, allocated_kwh, compensated_kwh,
                 billed_consumption_kwh, previous_credit_kwh, ending_credit_kwh, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    beneficiary["id"],
                    reading["reference_month"],
                    allocated,
                    compensated,
                    round(compensated * 1.05, 1),
                    previous_credit,
                    ending_credit,
                    "Rateio mensal conferido.",
                ),
            )

    tasks = [
        (1, 1, "Enviar relatório mensal do Mercado Bom Dia", "Relatório", "Alta", _iso_days(2), "Mensal", "Pendente", "Ana", "Consolidar as duas unidades."),
        (1, 2, "Inspecionar string 7 do Centro de Distribuição", "Manutenção corretiva", "Crítica", _iso_days(1), "Única", "Em andamento", "Rafael", "Levar alicate amperímetro e termovisor."),
        (2, 3, "Revisão preventiva semestral", "Manutenção preventiva", "Média", _iso_days(17), "Semestral", "Pendente", "Rafael", "Confirmar acesso com o proprietário."),
        (3, 4, "Reunião trimestral de resultados", "Relacionamento", "Média", _iso_days(26), "Trimestral", "Pendente", "Ana", "Preparar comparativo de economia acumulada."),
        (1, 2, "Limpeza dos módulos do CD", "Limpeza", "Alta", _iso_days(-4), "Trimestral", "Atrasada", "Equipe técnica", "Orçamento aprovado."),
    ]
    conn.executemany(
        """INSERT INTO tasks
        (client_id, plant_id, title, category, priority, due_date, recurrence, status, assignee, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        tasks,
    )

    tickets = [
        (1, 2, _iso_days(-3), "Oscilação de geração na string 7", "Geração", "Alta", "Em atendimento", 8, None, "Em diagnóstico", "Inspeção presencial agendada", "Alarme intermitente no inversor 2."),
        (2, 3, _iso_days(-18), "Portal de monitoramento sem atualizar", "Monitoramento", "Média", "Resolvido", 24, _iso_days(-17), "Falha de comunicação do datalogger", "Reinício remoto e atualização de firmware", "Cliente comunicado por WhatsApp."),
    ]
    conn.executemany(
        """INSERT INTO tickets
        (client_id, plant_id, opened_at, title, category, severity, status, sla_hours,
         resolved_at, root_cause, resolution, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        tickets,
    )

    contract_values = {1: 1127.27, 2: 398.08, 3: 1039.20}
    for contract_id, value in contract_values.items():
        for month in month_starts[-3:]:
            due = f"{month[:8]}10"
            status = "Pago" if month != month_starts[-1] else "Pendente"
            paid_at = f"{month[:8]}08" if status == "Pago" else None
            conn.execute(
                """INSERT INTO invoices
                (contract_id, reference_month, due_date, amount, status, paid_at, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (contract_id, month, due, value, status, paid_at, "Mensalidade de pós-venda"),
            )


def _iso_days(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _recent_months(count: int) -> list[str]:
    current = date.today().replace(day=1)
    months: list[str] = []
    for offset in range(count - 1, -1, -1):
        year = current.year
        month = current.month - offset
        while month <= 0:
            month += 12
            year -= 1
        months.append(date(year, month, 1).isoformat())
    return months


def query(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
    finally:
        conn.close()


def query_one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def query_df(sql: str, params: Iterable[Any] = ()) -> pd.DataFrame:
    if using_postgres():
        conn = connect()
        try:
            cursor = conn.execute(sql, tuple(params))
            rows = cursor.fetchall()
            columns = [column.name for column in (cursor.description or [])]
            return pd.DataFrame([dict(row) for row in rows], columns=columns)
        finally:
            conn.close()
    conn = connect()
    try:
        return pd.read_sql_query(sql, conn, params=tuple(params))
    finally:
        conn.close()


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    conn = connect()
    try:
        statement = sql
        wants_id = using_postgres() and sql.lstrip().upper().startswith("INSERT")
        if wants_id and " RETURNING " not in sql.upper():
            statement = f"{sql.rstrip().rstrip(';')} RETURNING id"
        cursor = conn.execute(statement, tuple(params))
        inserted_id = 0
        if wants_id:
            row = cursor.fetchone()
            inserted_id = int(row["id"] if isinstance(row, dict) else row[0]) if row else 0
        else:
            inserted_id = int(getattr(cursor, "lastrowid", 0) or 0)
        conn.commit()
        return inserted_id
    finally:
        conn.close()


def execute_many(sql: str, rows: Iterable[Iterable[Any]]) -> None:
    conn = connect()
    try:
        conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()


def clear_business_data() -> None:
    """Remove demo/operational records while preserving company settings."""
    conn = connect()
    try:
        conn.execute("DELETE FROM sizing_projects")
        conn.execute("DELETE FROM pv_modules")
        conn.execute("DELETE FROM pv_inverters")
        conn.execute("DELETE FROM proposals")
        conn.execute("DELETE FROM opportunities")
        conn.execute("DELETE FROM site_inspections")
        conn.execute("DELETE FROM service_orders")
        conn.execute("DELETE FROM service_contracts")
        conn.execute("DELETE FROM cash_transactions")
        conn.execute("DELETE FROM clients")
        conn.commit()
    finally:
        conn.close()


def upsert_reading(values: dict[str, Any]) -> int:
    columns = [
        "plant_id", "reference_month", "consumption_kwh", "generation_kwh",
        "injected_kwh", "compensated_kwh", "tariff", "billed_amount",
        "reference_amount", "availability_pct", "performance_ratio",
        "downtime_hours", "incidents", "failure_notes", "meter_reading",
    ]
    params = [values.get(column) for column in columns]
    assignments = ", ".join(f"{column}=excluded.{column}" for column in columns[2:])
    sql = f"""INSERT INTO readings ({', '.join(columns)})
    VALUES ({', '.join('?' for _ in columns)})
    ON CONFLICT(plant_id, reference_month) DO UPDATE SET {assignments}"""
    return execute(sql, params)


def upsert_beneficiary_reading(values: dict[str, Any]) -> int:
    columns = [
        "beneficiary_id", "reference_month", "allocated_kwh", "compensated_kwh",
        "billed_consumption_kwh", "previous_credit_kwh", "ending_credit_kwh", "notes",
    ]
    params = [values.get(column) for column in columns]
    assignments = ", ".join(f"{column}=excluded.{column}" for column in columns[2:])
    sql = f"""INSERT INTO beneficiary_readings ({', '.join(columns)})
    VALUES ({', '.join('?' for _ in columns)})
    ON CONFLICT(beneficiary_id, reference_month) DO UPDATE SET {assignments}"""
    return execute(sql, params)


def dashboard_metrics(reference_month: str | None = None) -> dict[str, Any]:
    month = reference_month or date.today().replace(day=1).isoformat()
    active = query_one("SELECT COUNT(*) AS value FROM clients WHERE status='Ativo'")["value"]
    plant_row = query_one(
        "SELECT COUNT(*) AS plants, COALESCE(SUM(installed_kwp),0) AS kwp FROM plants WHERE status!='Desativada'"
    )
    reading = query_one(
        """SELECT COALESCE(SUM(generation_kwh),0) AS generation,
                  COALESCE(SUM(reference_amount-billed_amount),0) AS savings,
                  COALESCE(AVG(availability_pct),0) AS availability
           FROM readings WHERE reference_month=?""",
        (month,),
    )
    tasks = query_one(
        """SELECT SUM(CASE WHEN date(due_date)<date('now') AND status NOT IN ('Concluída','Cancelada') THEN 1 ELSE 0 END) AS overdue,
                  SUM(CASE WHEN status NOT IN ('Concluída','Cancelada') THEN 1 ELSE 0 END) AS open_tasks
           FROM tasks"""
    )
    mrr_rows = query(
        """SELECT c.*, COUNT(p.id) AS plant_count, COALESCE(SUM(p.installed_kwp),0) AS total_kwp
           FROM contracts c LEFT JOIN plants p ON p.client_id=c.client_id
           WHERE c.status='Ativo' GROUP BY c.id"""
    )
    from solar_crm.calculations import contract_monthly_value
    mrr = sum(contract_monthly_value(row, row["plant_count"], row["total_kwp"]) for row in mrr_rows)
    return {
        "active_clients": active,
        "plants": plant_row["plants"],
        "kwp": plant_row["kwp"],
        "generation": reading["generation"],
        "savings": reading["savings"],
        "availability": reading["availability"],
        "overdue": tasks["overdue"] or 0,
        "open_tasks": tasks["open_tasks"] or 0,
        "mrr": mrr,
    }


def available_months() -> list[str]:
    rows = query("SELECT DISTINCT reference_month FROM readings ORDER BY reference_month DESC")
    return [row["reference_month"] for row in rows]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
