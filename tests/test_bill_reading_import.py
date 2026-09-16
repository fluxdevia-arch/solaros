from __future__ import annotations

import unittest

from solar_crm.bill_audit import BillAudit
from solar_crm.bill_reading_import import (
    beneficiary_values_from_bill,
    find_bill_target,
    normalize_unit_code,
    reading_values_from_bill,
)


class BillReadingImportTests(unittest.TestCase):
    def setUp(self):
        self.audit = BillAudit(
            source_filename="fatura.pdf",
            unit_code="1.157.384",
            reference_month="2026-08",
            consumption_kwh=10168,
            injected_measured_kwh=None,
            compensated_kwh=8767,
            credit_balance_kwh=4462,
            gross_consumption_cost=9462.82,
            invoice_amount=1531.98,
            estimated_without_solar=9621.81,
        )

    def test_matches_formatted_unit_code_to_registered_plant(self):
        plants = [{"id": 7, "unit_code": "1157384", "name": "Usina Centro"}]
        target_type, target = find_bill_target(self.audit.unit_code, plants, [])

        self.assertEqual(normalize_unit_code(self.audit.unit_code), "1157384")
        self.assertEqual(target_type, "plant")
        self.assertEqual(target["id"], 7)

    def test_maps_invoice_and_preserves_existing_monitoring_values(self):
        plant = {"id": 7}
        existing = {
            "generation_kwh": 9200,
            "injected_kwh": 5100,
            "availability_pct": 98.5,
            "performance_ratio": 92.1,
            "downtime_hours": 2.5,
            "incidents": 1,
            "failure_notes": "Falha de comunicação no dia 12.",
            "meter_reading": "Portal do inversor",
        }

        values = reading_values_from_bill(self.audit, plant, existing)

        self.assertEqual(values["reference_month"], "2026-08-01")
        self.assertEqual(values["consumption_kwh"], 10168)
        self.assertEqual(values["compensated_kwh"], 8767)
        self.assertAlmostEqual(values["tariff"], 0.930647, places=6)
        self.assertEqual(values["billed_amount"], 1531.98)
        self.assertEqual(values["reference_amount"], 9621.81)
        self.assertEqual(values["generation_kwh"], 9200)
        self.assertEqual(values["injected_kwh"], 5100)
        self.assertEqual(values["availability_pct"], 98.5)
        self.assertEqual(values["failure_notes"], "Falha de comunicação no dia 12.")
        self.assertEqual(values["meter_reading"], "Portal do inversor | Fatura Energisa: fatura.pdf")

    def test_maps_beneficiary_invoice_and_preserves_allocation(self):
        beneficiary = {"id": 12}
        existing = {"allocated_kwh": 9000, "previous_credit_kwh": 2000, "notes": "Rateio conferido"}

        values = beneficiary_values_from_bill(self.audit, beneficiary, existing)

        self.assertEqual(values["reference_month"], "2026-08-01")
        self.assertEqual(values["allocated_kwh"], 9000)
        self.assertEqual(values["billed_consumption_kwh"], 10168)
        self.assertEqual(values["compensated_kwh"], 8767)
        self.assertEqual(values["previous_credit_kwh"], 2000)
        self.assertEqual(values["ending_credit_kwh"], 4462)
        self.assertEqual(values["notes"], "Rateio conferido | Importado da fatura Energisa: fatura.pdf")


if __name__ == "__main__":
    unittest.main()
