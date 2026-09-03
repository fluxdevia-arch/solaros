import unittest

from solar_crm.sizing import (
    circuit_current,
    energisa_pb_service_category,
    size_cable,
    size_conduit,
    size_pv_system,
    size_strings,
)


class SizingTests(unittest.TestCase):
    def test_residential_pv_system(self):
        result = size_pv_system(650, 95, 5.4, 80, 585, 6, 2.58)
        self.assertEqual(result.module_count, 9)
        self.assertAlmostEqual(result.installed_kwp, 5.265)
        self.assertGreater(result.estimated_monthly_kwh, 600)

    def test_string_limits_and_current(self):
        result = size_strings(10, 52.1, 44, 14.3, -0.25, -0.29, 12, 70, 600, 80, 550, 2, 32, 10)
        self.assertTrue(result.valid)
        self.assertGreaterEqual(result.max_modules_series, 10)
        self.assertLessEqual(result.min_modules_series, 10)
        self.assertAlmostEqual(result.current_per_mppt_a, 17.875)

    def test_three_phase_current_and_cable(self):
        current = circuit_current(20, 380, "Trifásico", 1, 0.98)
        self.assertAlmostEqual(current, 31.0, places=1)
        cable = size_cable(current, 380, 30, "Trifásico", 1.5, 1.25, 0.8, 3)
        self.assertGreaterEqual(cable.reference_ampacity_a * 0.8, cable.design_current_a)
        self.assertLessEqual(cable.voltage_drop_pct, 1.5)

    def test_conduit_and_energisa_pb(self):
        conduit = size_conduit([(2, 6.5), (1, 5.8)], 40)
        self.assertTrue(conduit.valid)
        self.assertLessEqual(conduit.occupancy_pct, 40)
        self.assertEqual(energisa_pb_service_category("Monofásico 230 V", 9.0)["category"], "M2")
        self.assertEqual(energisa_pb_service_category("Trifásico 380/220 V", 40.0)["category"], "T3")
        self.assertIsNone(energisa_pb_service_category("Monofásico 230 V", 25.0))


if __name__ == "__main__":
    unittest.main()
