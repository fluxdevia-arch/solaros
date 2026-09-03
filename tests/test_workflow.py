import os
import unittest
import uuid
from pathlib import Path

from solar_crm.db import init_db, query_one
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


if __name__ == "__main__":
    unittest.main()
