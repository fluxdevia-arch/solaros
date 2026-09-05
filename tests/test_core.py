import os
import unittest
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from solar_crm.calculations import (
    calculate_coverage,
    calculate_performance,
    calculate_savings,
    calculate_service_price,
)


class CalculationTests(unittest.TestCase):
    def test_savings_never_negative(self):
        self.assertEqual(calculate_savings(800, 1000), 0)
        self.assertEqual(calculate_savings(1000, 380.55), 619.45)

    def test_energy_ratios(self):
        self.assertEqual(calculate_coverage(800, 1000), 80)
        self.assertEqual(calculate_coverage(800, 0), 0)
        self.assertEqual(calculate_performance(950, 1000), 95)

    def test_pricing_breakdown(self):
        result = calculate_service_price(300, 2, 100, 50, 2, 50, 10)
        self.assertEqual(result.monthly_total, 585)
        self.assertEqual(result.annual_total, 7020)


class DatabaseAndPdfTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.db_path = temp_root / f"core-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        self.db_path.unlink(missing_ok=True)

    def test_seed_dashboard_and_pdf(self):
        from solar_crm.db import available_months, clear_business_data, dashboard_metrics, execute, init_db, query_one, upsert_beneficiary_reading
        from solar_crm.pdf_report import generate_client_report

        init_db(seed=True)
        metrics = dashboard_metrics(available_months()[0])
        self.assertEqual(metrics["active_clients"], 3)
        self.assertEqual(metrics["plants"], 4)
        self.assertGreater(metrics["mrr"], 0)
        self.assertEqual(query_one("SELECT COUNT(*) AS value FROM beneficiaries")["value"], 9)
        beneficiary = query_one("SELECT id FROM beneficiaries ORDER BY id LIMIT 1")
        upsert_beneficiary_reading({
            "beneficiary_id": beneficiary["id"],
            "reference_month": available_months()[0],
            "allocated_kwh": 321.5,
            "compensated_kwh": 280.0,
            "billed_consumption_kwh": 410.0,
            "previous_credit_kwh": 45.0,
            "ending_credit_kwh": 86.5,
            "notes": "Conferido em teste",
        })
        saved_allocation = query_one(
            "SELECT * FROM beneficiary_readings WHERE beneficiary_id=? AND reference_month=?",
            (beneficiary["id"], available_months()[0]),
        )
        self.assertEqual(saved_allocation["allocated_kwh"], 321.5)

        client = query_one("SELECT id FROM clients ORDER BY id LIMIT 1")
        pdf = generate_client_report(client["id"], available_months()[0])
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 7000)
        settings = query_one("SELECT * FROM settings WHERE id=1")
        self.assertEqual(settings["technical_name"], "Carlos Jessé Soares")
        self.assertEqual(settings["technical_registration"], "CFT: 11551320410")

        execute(
            """INSERT INTO cash_transactions
               (transaction_type, category, competence_month, issue_date, due_date, amount, status, description)
               VALUES ('Receita','Manutenção preventiva','2026-09-01','2026-09-01','2026-09-10',850,'A receber','Revisão anual')"""
        )
        self.assertEqual(
            query_one(
                "SELECT COUNT(*) AS value FROM cash_transactions WHERE description='Revisão anual'"
            )["value"],
            1,
        )
        self.assertEqual(
            query_one(
                "SELECT COUNT(*) AS value FROM cash_transactions WHERE source_type='invoice'"
            )["value"],
            9,
        )
        init_db(seed=True)
        self.assertEqual(
            query_one(
                "SELECT COUNT(*) AS value FROM cash_transactions WHERE source_type='invoice'"
            )["value"],
            9,
        )

        clear_business_data()
        init_db(seed=True)
        self.assertEqual(query_one("SELECT COUNT(*) AS value FROM clients")["value"], 0)
        self.assertEqual(query_one("SELECT COUNT(*) AS value FROM beneficiaries")["value"], 0)
        self.assertEqual(query_one("SELECT COUNT(*) AS value FROM beneficiary_readings")["value"], 0)
        self.assertEqual(query_one("SELECT COUNT(*) AS value FROM cash_transactions")["value"], 0)

    def test_handwritten_signature_is_normalized_and_rendered(self):
        from solar_crm.db import available_months, execute, init_db, query_one
        from solar_crm.pdf_report import generate_client_report
        from solar_crm.signature import normalize_signature_image

        init_db(seed=True)
        source = Image.new("RGB", (800, 260), "white")
        draw = ImageDraw.Draw(source)
        draw.line([(130, 150), (250, 70), (360, 165), (500, 75), (650, 145)], fill="#173B72", width=12)
        raw = BytesIO()
        source.save(raw, format="JPEG", quality=90)

        normalized = normalize_signature_image(raw.getvalue())
        with Image.open(BytesIO(normalized)) as result:
            self.assertEqual(result.mode, "RGBA")
            self.assertLess(result.width, source.width)
            self.assertLess(result.height, source.height)
            self.assertEqual(result.getpixel((0, 0))[3], 0)

        execute(
            "UPDATE settings SET signature_image=?, signature_image_mime='image/png' WHERE id=1",
            (normalized,),
        )
        client = query_one("SELECT id FROM clients ORDER BY id LIMIT 1")
        pdf = generate_client_report(client["id"], available_months()[0])
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 6000)

    def test_white_label_settings_and_logo_normalization(self):
        from solar_crm.branding import configured_app_name, configured_logo, normalize_brand_logo
        from solar_crm.db import execute, init_db, query_one

        init_db(seed=False)
        settings = query_one("SELECT * FROM settings WHERE id=1")
        self.assertEqual(settings["app_name"], "SolarOS By OnGrid")
        self.assertIn("brand_logo", settings)

        source = Image.new("RGBA", (2400, 900), (15, 90, 170, 128))
        raw = BytesIO()
        source.save(raw, format="PNG")
        normalized = normalize_brand_logo(raw.getvalue())
        with Image.open(BytesIO(normalized)) as result:
            self.assertEqual(result.mode, "RGBA")
            self.assertLessEqual(result.width, 1800)
            self.assertLessEqual(result.height, 700)
            self.assertEqual(result.getpixel((0, 0))[3], 128)

        execute(
            "UPDATE settings SET app_name=?, brand_logo=?, brand_logo_mime='image/png' WHERE id=1",
            ("Portal Solar Cliente", normalized),
        )
        customized = query_one("SELECT * FROM settings WHERE id=1")
        self.assertEqual(configured_app_name(customized), "Portal Solar Cliente")
        self.assertEqual(configured_logo(customized), normalized)

    def test_seeded_database_integrity(self):
        from solar_crm.db import connect, init_db

        init_db(seed=True)
        conn = connect()
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_key_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            conn.close()

        self.assertEqual(integrity, "ok")
        self.assertEqual(foreign_key_violations, [])

    def test_existing_cash_table_is_migrated_for_contract_links(self):
        from solar_crm.db import SCHEMA, connect, init_db

        legacy_schema = SCHEMA.replace(
            "    source_type TEXT,\n    source_id INTEGER,\n    deleted_at TEXT,\n",
            "",
        )
        conn = connect()
        try:
            conn.executescript(legacy_schema)
            conn.commit()
        finally:
            conn.close()

        init_db(seed=False)
        conn = connect()
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(cash_transactions)").fetchall()}
        finally:
            conn.close()
        self.assertIn("source_type", columns)
        self.assertIn("source_id", columns)
        self.assertIn("deleted_at", columns)


if __name__ == "__main__":
    unittest.main()
