from __future__ import annotations

import secrets
from datetime import datetime
from io import BytesIO
from urllib.parse import quote

from PIL import Image, ImageOps

from solar_crm.db import connect, execute, execute_many, now_iso, query, query_one


INSPECTION_STATUSES = ["Rascunho", "Em andamento", "Concluída", "Requer retorno"]
INSPECTION_URGENCIES = ["Rotina", "Prioritária", "Urgente", "Crítica"]
ITEM_STATUSES = ["Não verificado", "Conforme", "Atenção", "Não conforme", "Não aplicável"]

DEFAULT_CHECKLIST = [
    ("Segurança e acesso", "Acesso ao local e à cobertura"),
    ("Segurança e acesso", "Condições para trabalho em altura"),
    ("Segurança e acesso", "Sinalização, bloqueio e uso de EPI/EPC"),
    ("Módulos e cobertura", "Integridade visual dos módulos"),
    ("Módulos e cobertura", "Sujeira, manchas, trincas ou pontos quentes visíveis"),
    ("Módulos e cobertura", "Fixação, grampos e estrutura"),
    ("Módulos e cobertura", "Telhado, vedação e sinais de infiltração"),
    ("Circuito CC", "Cabos solares, conectores e organização"),
    ("Circuito CC", "Tensão e corrente das strings"),
    ("Circuito CC", "Seccionamento, fusíveis e DPS CC"),
    ("Inversor e circuito CA", "Estado, ventilação e alarmes do inversor"),
    ("Inversor e circuito CA", "Cabos, conexões e aquecimento no circuito CA"),
    ("Inversor e circuito CA", "Disjuntor, seccionamento e DPS CA"),
    ("Aterramento e identificação", "Condutor de proteção e equipotencialização"),
    ("Aterramento e identificação", "SPDA, aterramento e integridade das conexões"),
    ("Aterramento e identificação", "Etiquetas, avisos e identificação dos circuitos"),
    ("Monitoramento e desempenho", "Datalogger, comunicação e portal de monitoramento"),
    ("Monitoramento e desempenho", "Geração instantânea e comparação com o esperado"),
]

INSPECTION_SCHEMA = """
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
    technician TEXT, contact_name TEXT, contact_phone TEXT, address TEXT NOT NULL,
    weather TEXT, ambient_temperature_c REAL, roof_type TEXT, roof_condition TEXT,
    access_condition TEXT, latitude REAL, longitude REAL, solar_orientation TEXT,
    azimuth_deg REAL, tilt_deg REAL, shading_level TEXT, shading_sources TEXT,
    dc_voltage_v REAL, dc_current_a REAL, ac_voltage_v REAL, ac_current_a REAL,
    insulation_mohm REAL, grounding_ohm REAL, generation_power_kw REAL,
    inverter_alarms TEXT, safety_risks TEXT, findings TEXT, actions_performed TEXT,
    recommendations TEXT, materials_needed TEXT, follow_up_date TEXT,
    client_acknowledgement TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS inspection_checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id INTEGER NOT NULL REFERENCES site_inspections(id) ON DELETE CASCADE,
    category TEXT NOT NULL, item TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Não verificado', notes TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(inspection_id, item)
);
CREATE TABLE IF NOT EXISTS inspection_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id INTEGER NOT NULL REFERENCES site_inspections(id) ON DELETE CASCADE,
    category TEXT NOT NULL, caption TEXT, filename TEXT,
    mime_type TEXT NOT NULL, image_data BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_site_inspections_status ON site_inspections(status, inspected_at);
CREATE INDEX IF NOT EXISTS idx_site_inspections_token ON site_inspections(public_token);
CREATE INDEX IF NOT EXISTS idx_inspection_items_inspection ON inspection_checklist_items(inspection_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_inspection_photos_inspection ON inspection_photos(inspection_id, created_at);
"""

_inspection_schema_ready = False


def ensure_inspection_schema() -> None:
    """Create the field tables even during a Streamlit hot deployment.

    Streamlit may reload a new page before re-importing the central database
    module. Keeping this idempotent migration beside the feature prevents a
    brief mixed-version process from reaching missing PostgreSQL tables.
    """
    global _inspection_schema_ready
    if _inspection_schema_ready:
        return
    conn = connect()
    try:
        if getattr(conn, "is_postgres", False):
            conn.execute("SELECT pg_advisory_xact_lock(1397705807)")
            postgres_schema = (
                INSPECTION_SCHEMA
                .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
                .replace(" REAL", " DOUBLE PRECISION")
                .replace(" BLOB", " BYTEA")
                .replace("DEFAULT CURRENT_TIMESTAMP", "DEFAULT (CURRENT_TIMESTAMP::TEXT)")
            )
            for statement in postgres_schema.split(";"):
                if statement.strip():
                    conn.execute(statement)
        else:
            conn.executescript(INSPECTION_SCHEMA)
        conn.commit()
        _inspection_schema_ready = True
    finally:
        conn.close()


def create_inspection(values: dict) -> int:
    ensure_inspection_schema()
    address = str(values.get("address") or "").strip()
    if not values.get("client_id") or not address:
        raise ValueError("Informe o cliente e o endereço da vistoria.")
    inspection_id = execute(
        """INSERT INTO site_inspections
           (public_token, client_id, plant_id, service_order_id, inspection_type,
            status, urgency, inspected_at, technician, contact_name, contact_phone,
            address, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            secrets.token_urlsafe(24), values["client_id"], values.get("plant_id"),
            values.get("service_order_id"), values.get("inspection_type") or "Vistoria técnica",
            values.get("status") or "Rascunho", values.get("urgency") or "Rotina",
            values.get("inspected_at") or now_iso(), values.get("technician"),
            values.get("contact_name"), values.get("contact_phone"), address, now_iso(),
        ),
    )
    number = f"VIS-{datetime.now():%Y}-{inspection_id:05d}"
    execute("UPDATE site_inspections SET number=? WHERE id=?", (number, inspection_id))
    execute_many(
        """INSERT INTO inspection_checklist_items
           (inspection_id, category, item, status, sort_order) VALUES (?, ?, ?, ?, ?)""",
        [
            (inspection_id, category, item, "Não verificado", position)
            for position, (category, item) in enumerate(DEFAULT_CHECKLIST, start=1)
        ],
    )
    return inspection_id


def inspection_by_token(token: str) -> dict | None:
    if not token or len(token) < 20:
        return None
    return query_one(
        """SELECT si.*, c.name AS client_name, c.document AS client_document,
                  p.name AS plant_name, p.unit_code, p.inverter, p.modules,
                  so.number AS service_order_number, so.title AS service_order_title
           FROM site_inspections si
           JOIN clients c ON c.id=si.client_id
           LEFT JOIN plants p ON p.id=si.plant_id
           LEFT JOIN service_orders so ON so.id=si.service_order_id
           WHERE si.public_token=?""",
        (token,),
    )


def inspection_details(inspection_id: int) -> dict | None:
    return query_one(
        """SELECT si.*, c.name AS client_name, c.document AS client_document,
                  p.name AS plant_name, p.unit_code, p.inverter, p.modules,
                  so.number AS service_order_number, so.title AS service_order_title
           FROM site_inspections si
           JOIN clients c ON c.id=si.client_id
           LEFT JOIN plants p ON p.id=si.plant_id
           LEFT JOIN service_orders so ON so.id=si.service_order_id
           WHERE si.id=?""",
        (inspection_id,),
    )


def inspection_share_url(inspection: dict, base_url: str) -> str:
    base = (base_url or "http://localhost:8501").strip().rstrip("/")
    return f"{base}/?inspection={quote(inspection['public_token'])}"


def update_inspection(inspection_id: int, values: dict, checklist: list[dict]) -> None:
    status = values.get("status") or "Em andamento"
    urgency = values.get("urgency") or "Rotina"
    if status not in INSPECTION_STATUSES:
        raise ValueError("Status de vistoria inválido.")
    if urgency not in INSPECTION_URGENCIES:
        raise ValueError("Nível de urgência inválido.")
    execute(
        """UPDATE site_inspections SET
           inspection_type=?, status=?, urgency=?, inspected_at=?, technician=?,
           contact_name=?, contact_phone=?, address=?, weather=?, ambient_temperature_c=?,
           roof_type=?, roof_condition=?, access_condition=?, latitude=?, longitude=?,
           solar_orientation=?, azimuth_deg=?, tilt_deg=?, shading_level=?, shading_sources=?,
           dc_voltage_v=?, dc_current_a=?, ac_voltage_v=?, ac_current_a=?, insulation_mohm=?,
           grounding_ohm=?, generation_power_kw=?, inverter_alarms=?, safety_risks=?, findings=?,
           actions_performed=?, recommendations=?, materials_needed=?, follow_up_date=?,
           client_acknowledgement=?, updated_at=? WHERE id=?""",
        (
            values.get("inspection_type") or "Vistoria técnica", status, urgency,
            values.get("inspected_at") or now_iso(), values.get("technician"),
            values.get("contact_name"), values.get("contact_phone"), values.get("address"),
            values.get("weather"), values.get("ambient_temperature_c"), values.get("roof_type"),
            values.get("roof_condition"), values.get("access_condition"), values.get("latitude"),
            values.get("longitude"), values.get("solar_orientation"), values.get("azimuth_deg"),
            values.get("tilt_deg"), values.get("shading_level"), values.get("shading_sources"),
            values.get("dc_voltage_v"), values.get("dc_current_a"), values.get("ac_voltage_v"),
            values.get("ac_current_a"), values.get("insulation_mohm"), values.get("grounding_ohm"),
            values.get("generation_power_kw"), values.get("inverter_alarms"),
            values.get("safety_risks"), values.get("findings"), values.get("actions_performed"),
            values.get("recommendations"), values.get("materials_needed"),
            values.get("follow_up_date"), values.get("client_acknowledgement"), now_iso(),
            inspection_id,
        ),
    )
    if checklist:
        execute_many(
            """INSERT INTO inspection_checklist_items
               (inspection_id, category, item, status, notes, sort_order)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(inspection_id, item) DO UPDATE SET
               category=excluded.category, status=excluded.status,
               notes=excluded.notes, sort_order=excluded.sort_order""",
            [
                (
                    inspection_id, row["category"], row["item"],
                    row.get("status") if row.get("status") in ITEM_STATUSES else "Não verificado",
                    row.get("notes"), row.get("sort_order") or position,
                )
                for position, row in enumerate(checklist, start=1)
            ],
        )


def compress_photo(image_bytes: bytes, max_side: int = 1600, quality: int = 82) -> tuple[bytes, str]:
    if not image_bytes:
        raise ValueError("A imagem está vazia.")
    with Image.open(BytesIO(image_bytes)) as source:
        normalized = ImageOps.exif_transpose(source).convert("RGB")
        normalized.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        output = BytesIO()
        normalized.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue(), "image/jpeg"


def add_inspection_photo(
    inspection_id: int,
    image_bytes: bytes,
    filename: str,
    category: str,
    caption: str = "",
) -> int:
    total = query_one("SELECT COUNT(*) AS value FROM inspection_photos WHERE inspection_id=?", (inspection_id,))
    if total and int(total["value"]) >= 20:
        raise ValueError("Esta vistoria já possui o limite de 20 fotos.")
    compressed, mime_type = compress_photo(image_bytes)
    photo_id = execute(
        """INSERT INTO inspection_photos
           (inspection_id, category, caption, filename, mime_type, image_data)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (inspection_id, category or "Outras evidências", caption.strip(), filename, mime_type, compressed),
    )
    execute("UPDATE site_inspections SET updated_at=? WHERE id=?", (now_iso(), inspection_id))
    return photo_id


def inspection_items(inspection_id: int) -> list[dict]:
    return query(
        "SELECT * FROM inspection_checklist_items WHERE inspection_id=? ORDER BY sort_order, id",
        (inspection_id,),
    )


def inspection_photos(inspection_id: int) -> list[dict]:
    return query(
        "SELECT * FROM inspection_photos WHERE inspection_id=? ORDER BY created_at, id",
        (inspection_id,),
    )


def completion_score(inspection_id: int) -> int:
    rows = inspection_items(inspection_id)
    if not rows:
        return 0
    checked = sum(1 for row in rows if row["status"] != "Não verificado")
    return round(checked / len(rows) * 100)
