from __future__ import annotations

from solar_crm.db import connect, execute, now_iso, query, query_one
from solar_crm.inspections import compress_photo


EQUIPMENT_TYPES = ["Inversor", "Painel solar", "String box", "Datalogger", "Outro"]
EQUIPMENT_STATUSES = ["Operando", "Atenção", "Parado", "Substituído", "Estoque"]
POWER_UNITS = ["W", "kW", "Wp", "kWp"]
MAX_PHOTOS_PER_EQUIPMENT = 8

EQUIPMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS plant_equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    equipment_type TEXT NOT NULL,
    manufacturer TEXT, model TEXT,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
    serial_numbers TEXT,
    nominal_power REAL NOT NULL DEFAULT 0,
    power_unit TEXT NOT NULL DEFAULT 'W',
    installation_date TEXT, warranty_expiry TEXT, location TEXT,
    status TEXT NOT NULL DEFAULT 'Operando', notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS plant_equipment_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id INTEGER NOT NULL REFERENCES plant_equipment(id) ON DELETE CASCADE,
    caption TEXT, filename TEXT, mime_type TEXT NOT NULL,
    image_data BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_plant_equipment_plant ON plant_equipment(plant_id, equipment_type);
CREATE INDEX IF NOT EXISTS idx_plant_equipment_photos ON plant_equipment_photos(equipment_id, created_at);
"""

_schema_ready = False


def ensure_equipment_inventory_schema() -> None:
    """Create inventory tables safely during a hot Streamlit deployment."""
    global _schema_ready
    if _schema_ready:
        return
    conn = connect()
    try:
        if getattr(conn, "is_postgres", False):
            conn.execute("SELECT pg_advisory_xact_lock(1397705807)")
            schema = (
                EQUIPMENT_SCHEMA
                .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
                .replace(" BLOB", " BYTEA")
                .replace(" REAL", " DOUBLE PRECISION")
                .replace("DEFAULT CURRENT_TIMESTAMP", "DEFAULT (CURRENT_TIMESTAMP::TEXT)")
            )
            for statement in schema.split(";"):
                if statement.strip():
                    conn.execute(statement)
        else:
            conn.executescript(EQUIPMENT_SCHEMA)
        conn.commit()
        _schema_ready = True
    finally:
        conn.close()


def normalize_serial_numbers(value: str) -> str:
    values = []
    for raw in str(value or "").replace(",", "\n").replace(";", "\n").splitlines():
        serial = raw.strip()
        if serial and serial not in values:
            values.append(serial)
    return "\n".join(values)


def create_equipment(plant_id: int, values: dict) -> int:
    ensure_equipment_inventory_schema()
    equipment_type = str(values.get("equipment_type") or "").strip()
    quantity = int(values.get("quantity") or 0)
    if equipment_type not in EQUIPMENT_TYPES:
        raise ValueError("Selecione um tipo de equipamento válido.")
    if quantity < 1:
        raise ValueError("A quantidade deve ser maior que zero.")
    return execute(
        """INSERT INTO plant_equipment
           (plant_id, equipment_type, manufacturer, model, quantity, serial_numbers,
            nominal_power, power_unit, installation_date, warranty_expiry, location,
            status, notes, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(plant_id), equipment_type, str(values.get("manufacturer") or "").strip(),
            str(values.get("model") or "").strip(), quantity,
            normalize_serial_numbers(values.get("serial_numbers") or ""),
            float(values.get("nominal_power") or 0), values.get("power_unit") or "W",
            values.get("installation_date"), values.get("warranty_expiry"),
            str(values.get("location") or "").strip(), values.get("status") or "Operando",
            str(values.get("notes") or "").strip(), now_iso(),
        ),
    )


def update_equipment(equipment_id: int, values: dict) -> None:
    quantity = int(values.get("quantity") or 0)
    if quantity < 1:
        raise ValueError("A quantidade deve ser maior que zero.")
    execute(
        """UPDATE plant_equipment SET equipment_type=?, manufacturer=?, model=?, quantity=?,
           serial_numbers=?, nominal_power=?, power_unit=?, installation_date=?,
           warranty_expiry=?, location=?, status=?, notes=?, updated_at=? WHERE id=?""",
        (
            values.get("equipment_type"), str(values.get("manufacturer") or "").strip(),
            str(values.get("model") or "").strip(), quantity,
            normalize_serial_numbers(values.get("serial_numbers") or ""),
            float(values.get("nominal_power") or 0), values.get("power_unit") or "W",
            values.get("installation_date"), values.get("warranty_expiry"),
            str(values.get("location") or "").strip(), values.get("status") or "Operando",
            str(values.get("notes") or "").strip(), now_iso(), int(equipment_id),
        ),
    )


def equipment_for_plant(plant_id: int) -> list[dict]:
    ensure_equipment_inventory_schema()
    return query(
        """SELECT e.*,
                  (SELECT COUNT(*) FROM plant_equipment_photos p WHERE p.equipment_id=e.id) AS photo_count
           FROM plant_equipment e WHERE e.plant_id=?
           ORDER BY CASE e.equipment_type WHEN 'Inversor' THEN 1 WHEN 'Painel solar' THEN 2 ELSE 3 END,
                    e.manufacturer, e.model, e.id""",
        (int(plant_id),),
    )


def equipment_summary_for_client(client_id: int) -> dict[int, dict[str, int]]:
    ensure_equipment_inventory_schema()
    rows = query(
        """SELECT e.plant_id, e.equipment_type, SUM(e.quantity) AS quantity
           FROM plant_equipment e JOIN plants p ON p.id=e.plant_id
           WHERE p.client_id=? GROUP BY e.plant_id, e.equipment_type""",
        (int(client_id),),
    )
    summary: dict[int, dict[str, int]] = {}
    for row in rows:
        summary.setdefault(int(row["plant_id"]), {})[row["equipment_type"]] = int(row["quantity"] or 0)
    return summary


def equipment_photos(equipment_id: int) -> list[dict]:
    ensure_equipment_inventory_schema()
    return query(
        "SELECT * FROM plant_equipment_photos WHERE equipment_id=? ORDER BY created_at, id",
        (int(equipment_id),),
    )


def add_equipment_photo(equipment_id: int, image_bytes: bytes, filename: str, caption: str = "") -> int:
    ensure_equipment_inventory_schema()
    total = query_one(
        "SELECT COUNT(*) AS value FROM plant_equipment_photos WHERE equipment_id=?",
        (int(equipment_id),),
    )
    if total and int(total["value"]) >= MAX_PHOTOS_PER_EQUIPMENT:
        raise ValueError(f"Este equipamento já possui o limite de {MAX_PHOTOS_PER_EQUIPMENT} fotos.")
    compressed, mime_type = compress_photo(image_bytes)
    return execute(
        """INSERT INTO plant_equipment_photos
           (equipment_id, caption, filename, mime_type, image_data) VALUES (?, ?, ?, ?, ?)""",
        (int(equipment_id), caption.strip(), filename, mime_type, compressed),
    )
