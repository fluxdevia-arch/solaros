import os
import tempfile
import unittest
import uuid
from pathlib import Path


TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "tests"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_TEMP_ROOT)


class FaultGuideTests(unittest.TestCase):
    def setUp(self):
        self.db_path = TEST_TEMP_ROOT / f"faults-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)
        from solar_crm.db import init_db

        init_db(seed=True)

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_catalog_supports_manufacturer_symptom_and_code_search(self):
        from solar_crm.faults import list_faults, matching_faults

        self.assertGreaterEqual(len(list_faults()), 12)
        by_symptom = matching_faults(
            manufacturer="Growatt",
            symptom_category="Rede elétrica",
        )
        self.assertTrue(by_symptom)
        self.assertTrue(all(row["manufacturer"] in {"Growatt", "Multimarcas"} for row in by_symptom))

        by_code = matching_faults(code_or_text="GRID-ISO-01")
        self.assertEqual(len(by_code), 1)
        self.assertEqual(by_code[0]["title"], "Resistência de isolamento baixa")

    def test_fault_case_creates_order_records_solution_and_recheck(self):
        from solar_crm.db import query_one
        from solar_crm.faults import (
            create_corrective_order,
            create_fault_case,
            list_fault_cases,
            matching_faults,
            record_recheck,
            record_solution,
        )

        fault = matching_faults(code_or_text="GRID-CC-01")[0]
        case_id = create_fault_case(
            {
                "fault_id": fault["id"],
                "client_id": 1,
                "plant_id": 1,
                "observed_at": "2026-09-23",
                "symptom_notes": "String 2 com corrente menor.",
                "measurements_before": "String 1: 10 A; string 2: 4 A.",
            }
        )
        order_id = create_corrective_order(
            case_id,
            scheduled_date="2026-09-24",
            assignee="Equipe técnica",
        )
        order = query_one("SELECT * FROM service_orders WHERE id=?", (order_id,))
        self.assertEqual(order["service_type"], "Manutenção corretiva")
        self.assertIn("GRID-CC-01", order["work_description"])

        record_solution(case_id, "Conector incompatível substituído.", "Par de conectores MC4")
        waiting = next(row for row in list_fault_cases() if row["id"] == case_id)
        self.assertEqual(waiting["status"], "Aguardando reverificação")

        record_recheck(
            case_id,
            checked_at="2026-09-25",
            technician="Equipe técnica",
            measurements_after="Strings 1 e 2: 10 A.",
            result="Resolvida",
            notes="Correntes equilibradas após reparo.",
        )
        resolved = next(row for row in list_fault_cases() if row["id"] == case_id)
        self.assertEqual(resolved["status"], "Resolvida")
        self.assertEqual(resolved["solved_at"], "2026-09-25")


if __name__ == "__main__":
    unittest.main()
