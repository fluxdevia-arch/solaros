import os
import unittest
import uuid
from datetime import date
from pathlib import Path

from solar_crm.db import dashboard_metrics, execute, init_db, query_one
from solar_crm.maintenance import (
    create_maintenance_plan,
    create_stock_item,
    generate_due_maintenance_orders,
    maintenance_plans,
    record_stock_movement,
    service_order_stock_movements,
    stock_items,
)


class MaintenanceAndStockTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.db_path = temp_root / f"maintenance-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)
        init_db(seed=False)
        self.client_id = execute(
            "INSERT INTO clients (name, state, status, address, contact_name, phone) VALUES (?, ?, 'Ativo', ?, ?, ?)",
            ("Cliente preventivo", "PB", "João Pessoa/PB", "Responsável", "83999990000"),
        )
        self.plant_id = execute(
            """INSERT INTO plants
               (client_id, name, unit_code, address, installed_kwp, expected_monthly_kwh, status)
               VALUES (?, ?, ?, ?, ?, ?, 'Operando')""",
            (self.client_id, "Usina teste", "UC-01", "João Pessoa/PB", 10, 0),
        )

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        self.db_path.unlink(missing_ok=True)

    def test_preventive_plan_generates_one_order_and_advances_due_date(self):
        plan_id = create_maintenance_plan({
            "client_id": self.client_id,
            "plant_id": self.plant_id,
            "name": "Preventiva semestral",
            "frequency_months": 6,
            "next_due_date": "2026-10-10",
            "lead_days": 30,
            "priority": "Média",
            "work_description": "Executar checklist preventivo completo.",
        })
        created = generate_due_maintenance_orders(as_of=date(2026, 9, 23), horizon_days=0)
        self.assertEqual(len(created), 1)
        order = query_one("SELECT * FROM service_orders WHERE id=?", (created[0],))
        self.assertEqual(order["scheduled_date"], "2026-10-10")
        self.assertEqual(order["service_type"], "Manutenção preventiva")
        plan = next(row for row in maintenance_plans() if row["id"] == plan_id)
        self.assertEqual(plan["next_due_date"], "2027-04-10")
        self.assertEqual(generate_due_maintenance_orders(as_of=date(2026, 9, 23), horizon_days=0), [])

    def test_stock_balance_and_service_order_consumption(self):
        item_id = create_stock_item({
            "sku": "DPS-001", "name": "DPS CC", "unit": "un",
            "minimum_quantity": 2, "initial_quantity": 5, "unit_cost": 80,
        })
        order_id = execute(
            """INSERT INTO service_orders
               (public_token, number, client_id, plant_id, title, service_type, priority, status,
                requested_at, address, work_description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, "OS-TESTE", self.client_id, self.plant_id, "Troca de DPS", "Manutenção corretiva", "Alta", "Aberta", "2026-09-23", "João Pessoa/PB", "Substituir DPS"),
        )
        record_stock_movement(item_id, "Saída", 2, service_order_id=order_id, notes="DPS substituídos")
        item = next(row for row in stock_items() if row["id"] == item_id)
        self.assertEqual(float(item["balance"]), 3.0)
        self.assertEqual(service_order_stock_movements(order_id)[0]["item_name"], "DPS CC")
        with self.assertRaises(ValueError):
            record_stock_movement(item_id, "Saída", 4, service_order_id=order_id)

    def test_dashboard_estimates_generation_and_savings_without_reading(self):
        metrics = dashboard_metrics("2026-09-01")
        self.assertEqual(float(metrics["generation"]), 1500.0)
        self.assertEqual(float(metrics["savings"]), 1425.0)
        self.assertEqual(int(metrics["estimated_plants"]), 1)


if __name__ == "__main__":
    unittest.main()
