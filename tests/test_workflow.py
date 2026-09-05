import os
import unittest
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image

from solar_crm.db import init_db, query_one
from solar_crm.inspection_documents import generate_inspection_pdf
from solar_crm.inspections import (
    add_inspection_photo,
    create_inspection,
    inspection_by_token,
    inspection_details,
    inspection_items,
    inspection_share_url,
    update_inspection,
)
from solar_crm.service_documents import generate_service_contract_pdf, generate_service_order_pdf
from solar_crm.workflow import (
    create_opportunity,
    create_service_contract,
    create_service_order,
    move_opportunity,
    regenerate_service_order_token,
    service_order_by_token,
    service_order_share_url,
    update_service_order,
)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.db_path = temp_root / f"workflow-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)
        init_db(seed=True)

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        self.db_path.unlink(missing_ok=True)

    def test_opportunity_moves_across_kanban(self):
        opportunity_id = create_opportunity({
            "lead_name": "Padaria Sol Nascente",
            "service_type": "Pós-venda solar",
            "estimated_value": 1200,
            "probability_pct": 30,
        })
        self.assertEqual(move_opportunity(opportunity_id, 1), "Diagnóstico")
        row = query_one("SELECT * FROM opportunities WHERE id=?", (opportunity_id,))
        self.assertEqual(row["stage"], "Diagnóstico")

    def test_service_order_link_update_and_pdf(self):
        client = query_one("SELECT id FROM clients ORDER BY id LIMIT 1")
        plant = query_one("SELECT id, address FROM plants WHERE client_id=? ORDER BY id LIMIT 1", (client["id"],))
        order_id = create_service_order({
            "client_id": client["id"],
            "plant_id": plant["id"],
            "title": "Inspeção elétrica",
            "service_type": "Inspeção técnica",
            "address": plant["address"],
            "work_description": "Verificar conexões, proteções e registrar medições.",
        })
        order = query_one("SELECT * FROM service_orders WHERE id=?", (order_id,))
        self.assertTrue(order["number"].startswith("OS-"))
        self.assertIn(order["public_token"], service_order_share_url(order, "https://solar.exemplo.com/"))
        self.assertEqual(service_order_by_token(order["public_token"])["id"], order_id)
        old_token = order["public_token"]
        new_token = regenerate_service_order_token(order_id)
        self.assertIsNone(service_order_by_token(old_token))
        self.assertEqual(service_order_by_token(new_token)["id"], order_id)

        update_service_order(order_id, "Concluída", "Inspeção concluída sem anomalias.", "Carlos")
        updated = query_one("SELECT * FROM service_orders WHERE id=?", (order_id,))
        self.assertEqual(updated["status"], "Concluída")
        self.assertIsNotNone(updated["completed_at"])

        pdf = generate_service_order_pdf(order_id)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 3000)

    def test_service_contract_pdf(self):
        client = query_one("SELECT id FROM clients ORDER BY id LIMIT 1")
        contract_id = create_service_contract({
            "client_id": client["id"],
            "contract_type": "Consultoria técnica",
            "title": "Contrato de consultoria técnica em energia solar",
            "start_date": "2026-09-03",
            "end_date": "2027-09-03",
            "duration_months": 12,
            "amount": 4500,
            "billing_cycle": "Parcela única",
            "scope": "Diagnóstico energético e recomendações técnicas.",
            "venue": "João Pessoa/PB",
        })
        pdf = generate_service_contract_pdf(contract_id)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 4000)
        cash_entry = query_one(
            """SELECT * FROM cash_transactions
               WHERE source_type='service_contract' AND source_id=?""",
            (contract_id,),
        )
        self.assertIsNotNone(cash_entry)
        self.assertEqual(float(cash_entry["amount"]), 4500.0)
        self.assertEqual(cash_entry["status"], "A receber")

    def test_mobile_inspection_workflow_and_photographic_pdf(self):
        client = query_one("SELECT id FROM clients ORDER BY id LIMIT 1")
        plant = query_one("SELECT id, address FROM plants WHERE client_id=? ORDER BY id LIMIT 1", (client["id"],))
        inspection_id = create_inspection({
            "client_id": client["id"],
            "plant_id": plant["id"],
            "inspection_type": "Manutenção preventiva",
            "inspected_at": "2026-09-04",
            "technician": "Carlos Jessé",
            "address": plant["address"],
        })
        inspection = inspection_details(inspection_id)
        self.assertTrue(inspection["number"].startswith("VIS-"))
        self.assertEqual(inspection_by_token(inspection["public_token"])["id"], inspection_id)
        self.assertIn("inspection=", inspection_share_url(inspection, "https://solar.exemplo.com/"))

        items = inspection_items(inspection_id)
        self.assertGreaterEqual(len(items), 18)
        for item in items:
            item["status"] = "Conforme"
            item["notes"] = "Verificado em campo."
        update_inspection(inspection_id, {
            **inspection,
            "status": "Concluída",
            "urgency": "Rotina",
            "weather": "Ensolarado",
            "solar_orientation": "Norte",
            "azimuth_deg": 0,
            "tilt_deg": 18,
            "shading_level": "Baixo",
            "dc_voltage_v": 620,
            "dc_current_a": 13.4,
            "ac_voltage_v": 380,
            "ac_current_a": 57.2,
            "generation_power_kw": 35.8,
            "findings": "Sistema operando sem falhas críticas.",
            "actions_performed": "Reaperto e inspeção visual.",
            "recommendations": "Manter limpeza semestral.",
        }, items)

        photo_buffer = BytesIO()
        Image.new("RGB", (900, 600), "#F58220").save(photo_buffer, format="PNG")
        add_inspection_photo(inspection_id, photo_buffer.getvalue(), "modulos.png", "Módulos", "Vista geral do arranjo")
        pdf = generate_inspection_pdf(inspection_id)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 7000)


if __name__ == "__main__":
    unittest.main()
