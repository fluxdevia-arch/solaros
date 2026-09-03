from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from solar_crm.config import encryption_key  # noqa: E402
from solar_crm.db import PostgresConnection, SCHEMA, get_db_path  # noqa: E402
from solar_crm.secure_store import protect_secret, unprotect_secret  # noqa: E402


TABLES = [
    "settings",
    "clients",
    "plants",
    "contracts",
    "readings",
    "beneficiaries",
    "beneficiary_readings",
    "monitoring_integrations",
    "remote_plants",
    "plant_integrations",
    "telemetry_daily",
    "integration_sync_logs",
    "tasks",
    "tickets",
    "invoices",
    "cash_transactions",
    "opportunities",
    "service_orders",
    "service_contracts",
]

SERIAL_TABLES = [table for table in TABLES if table != "settings"]


def _reencrypt_integration(row: dict[str, object]) -> dict[str, object]:
    for column in ("credential_key_encrypted", "credential_secret_encrypted"):
        stored = str(row.get(column) or "")
        if stored:
            row[column] = protect_secret(unprotect_secret(stored))
    return row


def main() -> None:
    target_url = os.getenv("DATABASE_URL", "").strip()
    if not target_url:
        raise SystemExit("Defina DATABASE_URL com a URI PostgreSQL do Supabase.")
    if not encryption_key():
        raise SystemExit("Defina SOLAROS_ENCRYPTION_KEY antes da migração.")

    source_path = get_db_path()
    if not source_path.exists():
        raise SystemExit(f"Banco SQLite não encontrado: {source_path}")

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    target = PostgresConnection(target_url)
    try:
        target.executescript(SCHEMA)
        occupied = []
        for table in TABLES[1:]:
            row = target.execute(f"SELECT COUNT(*) AS value FROM {table}").fetchone()
            if int(row["value"]):
                occupied.append(table)
        if occupied:
            raise SystemExit(
                "Migração cancelada: o destino já possui dados em " + ", ".join(occupied) + "."
            )

        # A inicialização do app pode ter criado apenas a configuração padrão.
        target.execute("DELETE FROM settings")

        totals: dict[str, int] = {}
        for table in TABLES:
            rows = [dict(row) for row in source.execute(f"SELECT * FROM {table}").fetchall()]
            if table == "monitoring_integrations":
                rows = [_reencrypt_integration(row) for row in rows]
            totals[table] = len(rows)
            if not rows:
                continue
            columns = list(rows[0])
            placeholders = ", ".join("?" for _ in columns)
            column_sql = ", ".join(columns)
            target.executemany(
                f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                [[row[column] for column in columns] for row in rows],
            )

        for table in SERIAL_TABLES:
            target.execute(
                f"""SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {table}), 1),
                    EXISTS(SELECT 1 FROM {table})
                )"""
            )
        target.commit()
    except BaseException:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()

    total = sum(totals.values())
    print(f"Migração concluída: {total} registros copiados para o PostgreSQL.")
    for table, count in totals.items():
        print(f"- {table}: {count}")


if __name__ == "__main__":
    main()
