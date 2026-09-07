from __future__ import annotations

import os
import unittest
import uuid
from io import BytesIO
from pathlib import Path

import pandas as pd


def workbook_bytes(frame: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Dados", index=False)
    return buffer.getvalue()


class InverterCurveTests(unittest.TestCase):
    def test_shuffled_columns_and_vendor_aliases_are_recognized(self):
        from solar_crm.inverter_curve import analyze_inverter_curve

        frame = pd.DataFrame(
            {
                "PV2 Current [A]": [0, 5, 8, 4],
                "Yield Today (kWh)": [0, 1, 3, 4],
                "Horário": ["06:00", "09:00", "12:00", "15:00"],
                "AC Output Power (kW)": [0, 2, 4, 1],
                "PV1 Voltage (V)": [300, 310, 320, 305],
                "PV1 Current (A)": [0, 5.2, 8.1, 4.1],
                "PV2 Voltage (V)": [300, 309, 319, 304],
            }
        )
        result = analyze_inverter_curve(workbook_bytes(frame), "relatorio_2026-09-06.xlsx")

        self.assertEqual(result["summary"]["sample_count"], 4)
        self.assertEqual(result["summary"]["daily_energy_kwh"], 4)
        self.assertEqual(result["mapping"]["active_power_kw"], "AC Output Power (kW)")
        self.assertEqual(result["mapping"]["mppt_2_current_a"], "PV2 Current [A]")
        self.assertEqual(len(result["mppt_summary"]), 2)

    def test_manual_mapping_supports_unknown_manufacturer_headers(self):
        from solar_crm.inverter_curve import analyze_inverter_curve

        frame = pd.DataFrame(
            {
                "Amostra local": ["08:00", "08:05", "08:10"],
                "Canal X": [1.0, 2.0, 3.0],
                "Canal Y": [2.0, 4.0, 6.0],
            }
        )
        result = analyze_inverter_curve(
            workbook_bytes(frame),
            "fabricante.xlsx",
            column_mapping={
                "timestamp": "Amostra local",
                "active_power_kw": "Canal X",
                "mppt_1_current_a": "Canal Y",
            },
        )
        self.assertEqual(result["summary"]["peak_power_kw"], 3.0)
        self.assertIn("mppt_1_current_a", result["data"].columns)

    def test_curve_history_can_be_saved_and_deleted(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        db_path = temp_root / f"curve-{uuid.uuid4().hex}.db"
        previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(db_path)
        try:
            from solar_crm.db import execute, init_db, query_one
            from solar_crm.deletion import delete_record
            from solar_crm.inverter_curve import analyze_inverter_curve, save_curve_analysis

            init_db(seed=False)
            client_id = execute("INSERT INTO clients (name, status) VALUES ('Cliente', 'Ativo')")
            plant_id = execute("INSERT INTO plants (client_id, name) VALUES (?, 'Usina')", (client_id,))
            frame = pd.DataFrame({"Hora": ["10:00", "10:05", "10:10"], "Potência Ativa(kW)": [1, 2, 1]})
            result = analyze_inverter_curve(workbook_bytes(frame), "curva_2026-09-06.xlsx")
            analysis_id = save_curve_analysis(plant_id, "INV-01", "curva.xlsx", result)
            self.assertIsNotNone(query_one("SELECT id FROM inverter_curve_analyses WHERE id=?", (analysis_id,)))
            delete_record("inverter_curve_analysis", analysis_id)
            self.assertIsNone(query_one("SELECT id FROM inverter_curve_analyses WHERE id=?", (analysis_id,)))
        finally:
            if previous_db is None:
                os.environ.pop("SOLAR_CRM_DB", None)
            else:
                os.environ["SOLAR_CRM_DB"] = previous_db
            db_path.unlink(missing_ok=True)

    def test_pdf_contains_charts_findings_and_technical_signature(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        db_path = temp_root / f"curve-pdf-{uuid.uuid4().hex}.db"
        previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(db_path)
        try:
            from pypdf import PdfReader

            from solar_crm.curve_documents import generate_inverter_curve_pdf
            from solar_crm.db import execute, init_db
            from solar_crm.inverter_curve import analyze_inverter_curve

            init_db(seed=False)
            client_id = execute("INSERT INTO clients (name, status) VALUES ('Cliente PDF', 'Ativo')")
            plant_id = execute("INSERT INTO plants (client_id, name, unit_code) VALUES (?, 'Usina PDF', 'UC-01')", (client_id,))
            frame = pd.DataFrame({
                "Data (HH:mm)": ["08:00", "09:00", "10:00", "11:00", "12:00"],
                "Potência Ativa(kW)": [0.2, 2.0, 4.2, 3.8, 1.5],
                "Geração Hoje(kWh)": [0.1, 1.2, 3.5, 6.8, 8.5],
                "Corrente MPPT1(A)": [1, 5, 9, 8, 4],
                "Tensão MPPT1(V)": [300, 320, 330, 325, 315],
                "Temperatura interna(°C)": [35, 45, 55, 78, 62],
            })
            result = analyze_inverter_curve(workbook_bytes(frame), "curva-2026-09-06.xlsx")
            pdf = generate_inverter_curve_pdf(plant_id, "INV-01", "curva.xlsx", result)
            reader = PdfReader(BytesIO(pdf))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            self.assertGreaterEqual(len(reader.pages), 3)
            self.assertIn("Relatório técnico de análise diária", text)
            self.assertIn("Comportamento dos MPPTs / entradas CC", text)
            self.assertIn("Diagnóstico e recomendações", text)
            self.assertIn("Carlos Jessé Soares", text)
        finally:
            if previous_db is None:
                os.environ.pop("SOLAR_CRM_DB", None)
            else:
                os.environ["SOLAR_CRM_DB"] = previous_db
            db_path.unlink(missing_ok=True)

    def test_monthly_english_export_sums_days_and_reports_empty_string_channels(self):
        from solar_crm.inverter_curve import analyze_inverter_curve

        frame = pd.DataFrame({
            "serial number": ["INV-01"] * 6,
            "time": [
                "2026-08-10 08:00:00", "2026-08-10 12:00:00", "2026-08-10 17:00:00",
                "2026-08-11 08:00:00", "2026-08-11 12:00:00", "2026-08-11 17:00:00",
            ],
            "E-today(kWh)": [1, 10, 20, 2, 12, 25],
            "E-total(MWh)": [32.50, 32.51, 32.52, 32.52, 32.53, 32.55],
            "Active power(kW)": [1, 6, 0, 1, 7, 0],
            "DC current1(A)": [2, 9, 0, 2, 10, 0],
            "DC voltage1(V)": [300, 330, 290, 301, 331, 291],
            "String current1(A)": [None] * 6,
            "R-phase voltage(V)": [220, 225, 221, 219, 226, 220],
            "S-phase voltage(V)": [221, 224, 220, 220, 225, 221],
            "T-phase voltage(V)": [219, 223, 222, 221, 224, 222],
        })
        result = analyze_inverter_curve(workbook_bytes(frame), "INV_11_08_2026.xlsx")
        self.assertEqual(result["mapping"]["active_power_kw"], "Active power(kW)")
        self.assertEqual(result["summary"]["analysis_type"], "Período")
        self.assertEqual(result["summary"]["date_start"], "2026-08-10")
        self.assertEqual(result["summary"]["date_end"], "2026-08-11")
        self.assertEqual(result["summary"]["period_energy_kwh"], 45)
        self.assertEqual(result["coverage"]["recognized_string_channels"], 1)
        self.assertEqual(result["coverage"]["string_channels_with_values"], 0)
        self.assertTrue(any("string" in issue.parameter.lower() for issue in result["issues"]))

    def test_pdf_can_be_created_without_registered_client_or_plant(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        db_path = temp_root / f"standalone-pdf-{uuid.uuid4().hex}.db"
        previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(db_path)
        try:
            from pypdf import PdfReader

            from solar_crm.curve_documents import generate_inverter_curve_pdf
            from solar_crm.db import init_db
            from solar_crm.inverter_curve import analyze_inverter_curve

            init_db(seed=False)
            frame = pd.DataFrame({"time": ["2026-09-07 08:00", "2026-09-07 09:00", "2026-09-07 10:00"], "Active power(kW)": [1, 3, 2]})
            result = analyze_inverter_curve(workbook_bytes(frame), "curva.xlsx")
            pdf = generate_inverter_curve_pdf(
                None,
                "INV-15K",
                "curva.xlsx",
                result,
                report_context={"client_name": "Cliente avulso", "plant_name": "Usina avulsa", "address": "Patos - PB"},
            )
            text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
            self.assertIn("Cliente avulso", text)
            self.assertIn("Usina avulsa", text)
            self.assertIn("Patos - PB", text)
        finally:
            if previous_db is None:
                os.environ.pop("SOLAR_CRM_DB", None)
            else:
                os.environ["SOLAR_CRM_DB"] = previous_db
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
