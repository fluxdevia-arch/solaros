import os
import unittest
import uuid
from pathlib import Path


class SafeDeletionTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.db_path = temp_root / f"deletion-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)
        from solar_crm.db import init_db

        init_db(seed=False)

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        self.db_path.unlink(missing_ok=True)

    def _client(self, name: str = "Cliente teste") -> int:
        from solar_crm.db import execute

        return execute(
            "INSERT INTO clients (name, status) VALUES (?, 'Ativo')",
            (name,),
        )

    def test_invoice_deletion_removes_its_cash_entry(self):
        from solar_crm.db import execute, query_one
        from solar_crm.deletion import delete_record, deletion_impact

        client_id = self._client()
        contract_id = execute(
            """INSERT INTO contracts
               (client_id, plan, start_date, billing_day, billing_cycle, status)
               VALUES (?, 'Consultoria', '2026-09-01', 10, 'Parcela única', 'Ativo')""",
            (client_id,),
        )
        invoice_id = execute(
            """INSERT INTO invoices
               (contract_id, reference_month, due_date, amount, status)
               VALUES (?, '2026-09-01', '2026-09-10', 3000, 'Pendente')""",
            (contract_id,),
        )
        execute(
            """INSERT INTO cash_transactions
               (transaction_type, category, client_id, competence_month, issue_date, due_date,
                amount, status, description, source_type, source_id)
               VALUES ('Receita', 'Consultoria', ?, '2026-09-01', '2026-09-01',
                       '2026-09-10', 3000, 'A receber', 'Consultoria', 'invoice', ?)""",
            (client_id, invoice_id),
        )

        self.assertTrue(any("caixa" in item for item in deletion_impact("invoice", invoice_id)))
        delete_record("invoice", invoice_id)
        deleted_invoice = query_one("SELECT deleted_at FROM invoices WHERE id=?", (invoice_id,))
        self.assertIsNotNone(deleted_invoice["deleted_at"])
        self.assertIsNone(
            query_one(
                "SELECT id FROM cash_transactions WHERE source_type='invoice' AND source_id=?",
                (invoice_id,),
            )
        )

    def test_reading_deletion_removes_monthly_beneficiary_allocations(self):
        from solar_crm.db import execute, query_one
        from solar_crm.deletion import delete_record

        client_id = self._client()
        plant_id = execute(
            "INSERT INTO plants (client_id, name) VALUES (?, 'Usina teste')",
            (client_id,),
        )
        beneficiary_id = execute(
            """INSERT INTO beneficiaries (plant_id, name, unit_code, allocation_pct)
               VALUES (?, 'UC beneficiária', '12345', 100)""",
            (plant_id,),
        )
        reading_id = execute(
            """INSERT INTO readings (plant_id, reference_month, generation_kwh)
               VALUES (?, '2026-09-01', 850)""",
            (plant_id,),
        )
        execute(
            """INSERT INTO beneficiary_readings
               (beneficiary_id, reference_month, allocated_kwh)
               VALUES (?, '2026-09-01', 850)""",
            (beneficiary_id,),
        )

        delete_record("reading", reading_id)
        self.assertIsNone(query_one("SELECT id FROM readings WHERE id=?", (reading_id,)))
        self.assertIsNone(
            query_one(
                "SELECT id FROM beneficiary_readings WHERE beneficiary_id=? AND reference_month='2026-09-01'",
                (beneficiary_id,),
            )
        )

    def test_equipment_in_use_is_blocked_until_project_is_deleted(self):
        from solar_crm.db import execute, query_one
        from solar_crm.deletion import DeletionBlocked, delete_record

        module_id = execute(
            """INSERT INTO pv_modules
               (manufacturer, model, power_wp, voc_v, vmp_v, isc_a, imp_a)
               VALUES ('Marca', 'MOD-585', 585, 52, 44, 14, 13)"""
        )
        inverter_id = execute(
            """INSERT INTO pv_inverters
               (manufacturer, model, nominal_power_kw, max_dc_power_kw, max_dc_voltage_v,
                mppt_min_v, mppt_max_v, max_input_current_mppt_a,
                max_short_circuit_current_mppt_a)
               VALUES ('Marca', 'INV-6K', 6, 9, 600, 80, 550, 32, 40)"""
        )
        project_id = execute(
            """INSERT INTO sizing_projects
               (name, module_id, inverter_id, module_count, modules_per_string,
                layout_rows, layout_columns, result_json)
               VALUES ('Projeto teste', ?, ?, 12, 6, 2, 6, '{}')""",
            (module_id, inverter_id),
        )

        with self.assertRaises(DeletionBlocked):
            delete_record("pv_module", module_id)
        delete_record("sizing_project", project_id)
        delete_record("pv_module", module_id)
        delete_record("pv_inverter", inverter_id)
        self.assertIsNone(query_one("SELECT id FROM pv_modules WHERE id=?", (module_id,)))
        self.assertIsNone(query_one("SELECT id FROM pv_inverters WHERE id=?", (inverter_id,)))

    def test_client_deletion_cleans_documents_but_preserves_manual_cash(self):
        from solar_crm.db import execute, query_one
        from solar_crm.deletion import delete_record

        client_id = self._client()
        contract_id = execute(
            """INSERT INTO contracts
               (client_id, plan, start_date, billing_day, billing_cycle, status)
               VALUES (?, 'Mensal', '2026-09-01', 10, 'Mensal', 'Ativo')""",
            (client_id,),
        )
        invoice_id = execute(
            """INSERT INTO invoices
               (contract_id, reference_month, due_date, amount, status)
               VALUES (?, '2026-09-01', '2026-09-10', 600, 'Pendente')""",
            (contract_id,),
        )
        linked_cash_id = execute(
            """INSERT INTO cash_transactions
               (transaction_type, category, client_id, competence_month, issue_date, due_date,
                amount, status, description, source_type, source_id)
               VALUES ('Receita', 'Mensalidade', ?, '2026-09-01', '2026-09-01',
                       '2026-09-10', 600, 'A receber', 'Mensalidade', 'invoice', ?)""",
            (client_id, invoice_id),
        )
        manual_cash_id = execute(
            """INSERT INTO cash_transactions
               (transaction_type, category, client_id, competence_month, issue_date, due_date,
                amount, status, description)
               VALUES ('Receita', 'Outro', ?, '2026-09-01', '2026-09-01',
                       '2026-09-10', 100, 'Recebido', 'Lançamento manual')""",
            (client_id,),
        )

        delete_record("client", client_id)
        self.assertIsNone(query_one("SELECT id FROM clients WHERE id=?", (client_id,)))
        self.assertIsNone(query_one("SELECT id FROM cash_transactions WHERE id=?", (linked_cash_id,)))
        manual = query_one("SELECT client_id FROM cash_transactions WHERE id=?", (manual_cash_id,))
        self.assertIsNotNone(manual)
        self.assertIsNone(manual["client_id"])


if __name__ == "__main__":
    unittest.main()
