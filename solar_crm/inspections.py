from __future__ import annotations

import secrets
from datetime import datetime
from io import BytesIO
from urllib.parse import quote

from PIL import Image, ImageOps

from solar_crm.checklists import BASIC_INSPECTION_CHECKLIST
from solar_crm.db import connect, execute, execute_many, now_iso, query, query_one
from solar_crm.signature import normalize_signature_image
from solar_crm.workflow import create_service_order


INSPECTION_STATUSES = ["Rascunho", "Em andamento", "Concluída", "Requer retorno"]
INSPECTION_URGENCIES = ["Rotina", "Prioritária", "Urgente", "Crítica"]
ITEM_STATUSES = ["Não verificado", "Conforme", "Atenção", "Não conforme", "Não aplicável"]

DEFAULT_CHECKLIST = BASIC_INSPECTION_CHECKLIST

INSPECTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS inspection_checklist_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE, description TEXT,
    inspection_type TEXT NOT NULL DEFAULT 'Vistoria técnica', standard_reference TEXT,
    is_system INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS inspection_checklist_template_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL REFERENCES inspection_checklist_templates(id) ON DELETE CASCADE,
    category TEXT NOT NULL, item TEXT NOT NULL,
    requires_photo INTEGER NOT NULL DEFAULT 0, sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(template_id, item)
);
CREATE TABLE IF NOT EXISTS site_inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT UNIQUE,
    public_token TEXT NOT NULL UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    plant_id INTEGER REFERENCES plants(id) ON DELETE SET NULL,
    service_order_id INTEGER REFERENCES service_orders(id) ON DELETE SET NULL,
    template_id INTEGER REFERENCES inspection_checklist_templates(id) ON DELETE SET NULL,
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
    client_signer_name TEXT, client_signer_document TEXT,
    client_signature_image BLOB, client_signature_mime TEXT,
    client_signed_at TEXT, client_signature_consent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS inspection_checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id INTEGER NOT NULL REFERENCES site_inspections(id) ON DELETE CASCADE,
    category TEXT NOT NULL, item TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Não verificado', notes TEXT,
    requires_photo INTEGER NOT NULL DEFAULT 0, replacement_part TEXT,
    replacement_serial TEXT,
    corrective_order_id INTEGER REFERENCES service_orders(id) ON DELETE SET NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(inspection_id, item)
);
CREATE TABLE IF NOT EXISTS inspection_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id INTEGER NOT NULL REFERENCES site_inspections(id) ON DELETE CASCADE,
    checklist_item_id INTEGER REFERENCES inspection_checklist_items(id) ON DELETE SET NULL,
    category TEXT NOT NULL, caption TEXT, filename TEXT,
    mime_type TEXT NOT NULL, image_data BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_site_inspections_status ON site_inspections(status, inspected_at);
CREATE INDEX IF NOT EXISTS idx_site_inspections_token ON site_inspections(public_token);
CREATE INDEX IF NOT EXISTS idx_inspection_items_inspection ON inspection_checklist_items(inspection_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_inspection_photos_inspection ON inspection_photos(inspection_id, created_at);
CREATE INDEX IF NOT EXISTS idx_inspection_template_items ON inspection_checklist_template_items(template_id, sort_order);
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
        if getattr(conn, "is_postgres", False):
            conn.execute("ALTER TABLE site_inspections ADD COLUMN IF NOT EXISTS template_id BIGINT REFERENCES inspection_checklist_templates(id) ON DELETE SET NULL")
            for name, column_type in {
                "client_signer_name": "TEXT",
                "client_signer_document": "TEXT",
                "client_signature_image": "BYTEA",
                "client_signature_mime": "TEXT",
                "client_signed_at": "TEXT",
                "client_signature_consent": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                conn.execute(f"ALTER TABLE site_inspections ADD COLUMN IF NOT EXISTS {name} {column_type}")
            for name, column_type in {
                "requires_photo": "INTEGER NOT NULL DEFAULT 0",
                "replacement_part": "TEXT",
                "replacement_serial": "TEXT",
                "corrective_order_id": "BIGINT REFERENCES service_orders(id) ON DELETE SET NULL",
            }.items():
                conn.execute(f"ALTER TABLE inspection_checklist_items ADD COLUMN IF NOT EXISTS {name} {column_type}")
            conn.execute("ALTER TABLE inspection_photos ADD COLUMN IF NOT EXISTS checklist_item_id BIGINT REFERENCES inspection_checklist_items(id) ON DELETE SET NULL")
        else:
            additions = {
                "site_inspections": {
                    "template_id": "INTEGER REFERENCES inspection_checklist_templates(id) ON DELETE SET NULL",
                    "client_signer_name": "TEXT",
                    "client_signer_document": "TEXT",
                    "client_signature_image": "BLOB",
                    "client_signature_mime": "TEXT",
                    "client_signed_at": "TEXT",
                    "client_signature_consent": "INTEGER NOT NULL DEFAULT 0",
                },
                "inspection_checklist_items": {
                    "requires_photo": "INTEGER NOT NULL DEFAULT 0",
                    "replacement_part": "TEXT",
                    "replacement_serial": "TEXT",
                    "corrective_order_id": "INTEGER REFERENCES service_orders(id) ON DELETE SET NULL",
                },
                "inspection_photos": {"checklist_item_id": "INTEGER REFERENCES inspection_checklist_items(id) ON DELETE SET NULL"},
            }
            for table, columns in additions.items():
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for name, column_type in columns.items():
                    if name not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")
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
           (public_token, client_id, plant_id, service_order_id, template_id, inspection_type,
            status, urgency, inspected_at, technician, contact_name, contact_phone,
            address, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            secrets.token_urlsafe(24), values["client_id"], values.get("plant_id"),
            values.get("service_order_id"), values.get("template_id"), values.get("inspection_type") or "Vistoria técnica",
            values.get("status") or "Rascunho", values.get("urgency") or "Rotina",
            values.get("inspected_at") or now_iso(), values.get("technician"),
            values.get("contact_name"), values.get("contact_phone"), address, now_iso(),
        ),
    )
    number = f"VIS-{datetime.now():%Y}-{inspection_id:05d}"
    execute("UPDATE site_inspections SET number=? WHERE id=?", (number, inspection_id))
    template_items = inspection_template_items(values.get("template_id")) if values.get("template_id") else []
    source_items = template_items or [
        {"category": category, "item": item, "requires_photo": requires_photo, "sort_order": position}
        for position, (category, item, requires_photo) in enumerate(DEFAULT_CHECKLIST, start=1)
    ]
    execute_many(
        """INSERT INTO inspection_checklist_items
           (inspection_id, category, item, status, requires_photo, sort_order) VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (inspection_id, row["category"], row["item"], "Não verificado", int(row.get("requires_photo") or 0), row.get("sort_order") or position)
            for position, row in enumerate(source_items, start=1)
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
               (inspection_id, category, item, status, notes, requires_photo,
                replacement_part, replacement_serial, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(inspection_id, item) DO UPDATE SET
               category=excluded.category, status=excluded.status,
               notes=excluded.notes, requires_photo=excluded.requires_photo,
               replacement_part=excluded.replacement_part,
               replacement_serial=excluded.replacement_serial,
               sort_order=excluded.sort_order""",
            [
                (
                    inspection_id, row["category"], row["item"],
                    row.get("status") if row.get("status") in ITEM_STATUSES else "Não verificado",
                    row.get("notes"), int(row.get("requires_photo") or 0),
                    row.get("replacement_part"), row.get("replacement_serial"),
                    row.get("sort_order") or position,
                )
                for position, row in enumerate(checklist, start=1)
            ],
        )


def save_inspection_signature(
    inspection_id: int,
    signer_name: str,
    signer_document: str,
    signature_image: bytes,
    consent: bool,
) -> None:
    name = signer_name.strip()
    if not name or not signer_document.strip():
        raise ValueError("Informe o nome e o documento do responsável.")
    if not consent:
        raise ValueError("O responsável deve confirmar a ciência antes de assinar.")
    normalized = normalize_signature_image(signature_image)
    execute(
        """UPDATE site_inspections SET client_signer_name=?, client_signer_document=?,
           client_signature_image=?, client_signature_mime='image/png', client_signed_at=?,
           client_signature_consent=1, updated_at=? WHERE id=?""",
        (name, signer_document.strip(), normalized, now_iso(), now_iso(), inspection_id),
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
    checklist_item_id: int | None = None,
) -> int:
    total = query_one("SELECT COUNT(*) AS value FROM inspection_photos WHERE inspection_id=?", (inspection_id,))
    if total and int(total["value"]) >= 20:
        raise ValueError("Esta vistoria já possui o limite de 20 fotos.")
    compressed, mime_type = compress_photo(image_bytes)
    photo_id = execute(
        """INSERT INTO inspection_photos
           (inspection_id, checklist_item_id, category, caption, filename, mime_type, image_data)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (inspection_id, checklist_item_id, category or "Outras evidências", caption.strip(), filename, mime_type, compressed),
    )
    execute("UPDATE site_inspections SET updated_at=? WHERE id=?", (now_iso(), inspection_id))
    return photo_id


def inspection_items(inspection_id: int) -> list[dict]:
    return query(
        """SELECT ici.*, so.number AS corrective_order_number
           FROM inspection_checklist_items ici
           LEFT JOIN service_orders so ON so.id=ici.corrective_order_id
           WHERE ici.inspection_id=? ORDER BY ici.sort_order, ici.id""",
        (inspection_id,),
    )


def inspection_photos(inspection_id: int) -> list[dict]:
    return query(
        """SELECT ip.*, ici.item AS checklist_item
           FROM inspection_photos ip
           LEFT JOIN inspection_checklist_items ici ON ici.id=ip.checklist_item_id
           WHERE ip.inspection_id=? ORDER BY ip.created_at, ip.id""",
        (inspection_id,),
    )


def list_inspection_templates(active_only: bool = True) -> list[dict]:
    ensure_inspection_schema()
    where = "WHERE t.active=1" if active_only else ""
    return query(
        f"""SELECT t.*, COUNT(i.id) AS item_count
            FROM inspection_checklist_templates t
            LEFT JOIN inspection_checklist_template_items i ON i.template_id=t.id
            {where} GROUP BY t.id ORDER BY t.is_system DESC, t.name"""
    )


def inspection_template_items(template_id: int | None) -> list[dict]:
    if not template_id:
        return []
    return query(
        "SELECT * FROM inspection_checklist_template_items WHERE template_id=? ORDER BY sort_order, id",
        (template_id,),
    )


def create_inspection_template(values: dict) -> int:
    name = str(values.get("name") or "").strip()
    if not name:
        raise ValueError("Informe o nome do modelo.")
    template_id = execute(
        """INSERT INTO inspection_checklist_templates
           (name, description, inspection_type, standard_reference, is_system, active, updated_at)
           VALUES (?, ?, ?, ?, 0, 1, ?)""",
        (name, values.get("description"), values.get("inspection_type") or "Vistoria técnica", values.get("standard_reference"), now_iso()),
    )
    clone_from_id = values.get("clone_from_id")
    if clone_from_id:
        execute(
            """INSERT INTO inspection_checklist_template_items
               (template_id, category, item, requires_photo, sort_order)
               SELECT ?, category, item, requires_photo, sort_order
               FROM inspection_checklist_template_items WHERE template_id=?""",
            (template_id, clone_from_id),
        )
    return template_id


def add_inspection_template_item(template_id: int, category: str, item: str, requires_photo: bool = False) -> int:
    category = category.strip()
    item = item.strip()
    if not category or not item:
        raise ValueError("Informe o bloco e o item do checklist.")
    template = query_one("SELECT is_system FROM inspection_checklist_templates WHERE id=?", (template_id,))
    if not template or template["is_system"]:
        raise ValueError("Os modelos do sistema são protegidos. Crie uma cópia para personalizar.")
    position = query_one("SELECT COALESCE(MAX(sort_order), 0) + 1 AS value FROM inspection_checklist_template_items WHERE template_id=?", (template_id,))
    return execute(
        "INSERT INTO inspection_checklist_template_items (template_id, category, item, requires_photo, sort_order) VALUES (?, ?, ?, ?, ?)",
        (template_id, category, item, int(requires_photo), int(position["value"])),
    )


def create_corrective_order_from_item(item_id: int, scheduled_date: str | None = None, assignee: str = "") -> int:
    row = query_one(
        """SELECT ici.*, si.client_id, si.plant_id, si.number AS inspection_number,
                  si.address, si.contact_name, si.contact_phone, si.technician
           FROM inspection_checklist_items ici
           JOIN site_inspections si ON si.id=ici.inspection_id WHERE ici.id=?""",
        (item_id,),
    )
    if not row:
        raise ValueError("Item da vistoria não encontrado.")
    if row.get("corrective_order_id"):
        return int(row["corrective_order_id"])
    order_id = create_service_order({
        "client_id": row["client_id"], "plant_id": row.get("plant_id"),
        "title": f"Correção: {row['item']}", "service_type": "Manutenção corretiva",
        "priority": "Alta", "status": "Aberta", "scheduled_date": scheduled_date,
        "assignee": assignee or row.get("technician"), "address": row["address"],
        "contact_name": row.get("contact_name"), "contact_phone": row.get("contact_phone"),
        "work_description": f"Corrigir não conformidade identificada na {row['inspection_number']}: {row['item']}.\nObservação: {row.get('notes') or '-'}",
        "materials": row.get("replacement_part"),
        "safety_instructions": "Validar riscos, bloquear as fontes de energia e aplicar os procedimentos de segurança antes da intervenção.",
    })
    execute("UPDATE inspection_checklist_items SET corrective_order_id=? WHERE id=?", (order_id, item_id))
    execute("UPDATE site_inspections SET status='Requer retorno', updated_at=? WHERE id=?", (now_iso(), row["inspection_id"]))
    return order_id


def completion_score(inspection_id: int) -> int:
    rows = inspection_items(inspection_id)
    if not rows:
        return 0
    checked = sum(1 for row in rows if row["status"] != "Não verificado")
    return round(checked / len(rows) * 100)
