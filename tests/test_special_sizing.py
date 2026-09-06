import os
import unittest
import uuid
from pathlib import Path

from solar_crm.deletion import delete_record
from solar_crm.db import init_db, query_one
from solar_crm.records import create_special_sizing_project
from solar_crm.special_sizing import calculate_energy_system, calculate_solar_pumping


LOADS = [
    {
        "Equipamento": "Geladeira",
        "Quantidade": 1,
        "Potência unitária (W)": 250,
        "Horas/dia": 10,
        "Simultaneidade (%)": 60,
        "Prioritária": True,
        "Autonomia (h)": 8,
        "Pico de partida (x)": 3,
    },
    {
        "Equipamento": "Ar-condicionado",
        "Quantidade": 1,
        "Potência unitária (W)": 1200,
        "Horas/dia": 6,
        "Simultaneidade (%)": 100,
        "Prioritária": False,
        "Autonomia (h)": 0,
        "Pico de partida (x)": 2.5,
    },
]

INPUTS = {
    "monthly_bill_kwh": 450,
    "solar_coverage_pct": 100,
    "peak_sun_hours": 5.4,
    "performance_ratio_pct": 75,
    "module_power_wp": 585,
    "module_voc_v": 52.1,
    "module_vmp_v": 44,
    "module_isc_a": 14.3,
    "module_voc_coeff_pct": -0.25,
    "module_vmp_coeff_pct": -0.35,
    "minimum_temperature_c": 12,
    "maximum_cell_temperature_c": 70,
    "inverter_max_dc_voltage_v": 600,
    "inverter_mppt_min_v": 120,
    "inverter_mppt_max_v": 550,
    "inverter_mppt_count": 2,
    "inverter_max_current_mppt_a": 32,
    "modules_per_string": 6,
    "inverter_efficiency_pct": 95,
    "phases": "Monofásico",
    "ac_voltage_v": 230,
    "power_factor": 0.92,
    "design_margin_pct": 20,
    "battery_bank_voltage_v": 48,
    "battery_unit_voltage_v": 51.2,
    "battery_unit_ah": 100,
    "battery_dod_pct": 80,
    "battery_efficiency_pct": 92,
    "autonomy_days": 1,
    "battery_reserve_pct": 15,
    "dc_cable_length_m": 20,
    "battery_cable_length_m": 2,
    "ac_cable_length_m": 15,
    "voltage_drop_limit_pct": 2,
    "correction_factor": 0.8,
}


class SpecialSizingTests(unittest.TestCase):
    def test_hybrid_sizes_generation_backup_and_protections(self):
        result = calculate_energy_system("Híbrido conectado", LOADS, INPUTS)
        self.assertGreater(result["installed_pv_kwp"], 0)
        self.assertGreater(result["installed_battery_kwh"], 0)
        self.assertGreater(result["inverter_surge_kw"], result["backed_peak_kw"])
        self.assertTrue(any(row["Item"] == "Banco de baterias" for row in result["components"]))
        self.assertTrue(any(row["Item"] == "Quadro de cargas prioritárias" for row in result["components"]))

    def test_zero_grid_can_be_sized_without_batteries(self):
        result = calculate_energy_system("Zero grid", LOADS, {**INPUTS, "include_battery": False})
        self.assertEqual(result["battery_units"], 0)
        self.assertEqual(result["installed_battery_kwh"], 0)
        self.assertTrue(any(row["Item"] == "Controlador zero exportação" for row in result["components"]))
        self.assertTrue(any("NDU 013" in warning for warning in result["warnings"]))

    def test_off_grid_backs_up_all_loads(self):
        result = calculate_energy_system("Off-grid", LOADS, INPUTS)
        self.assertGreater(result["backed_peak_kw"], 1)
        self.assertGreater(result["backup_energy_kwh"], 0)
        self.assertGreater(result["battery_units"], 0)

    def test_solar_pumping_sizes_hydraulic_and_electrical_system(self):
        result = calculate_solar_pumping({
            "daily_volume_m3": 30,
            "total_head_m": 60,
            "pumping_hours_day": 6,
            "water_storage_days": 2,
            "pump_efficiency_pct": 55,
            "drive_efficiency_pct": 92,
            "peak_sun_hours": 5.4,
            "solar_derating_pct": 75,
            "module_power_wp": 585,
            "pipe_velocity_m_s": 1.5,
            "phases": "Trifásico",
            "ac_voltage_v": 380,
            "power_factor": 0.85,
            "cable_length_m": 50,
            "voltage_drop_limit_pct": 3,
            "correction_factor": 0.8,
        })
        self.assertAlmostEqual(result["flow_m3_h"], 5.0)
        self.assertGreater(result["pump_input_kw"], 0)
        self.assertGreater(result["installed_pv_kwp"], 0)
        self.assertEqual(result["reservoir_m3"], 60)
        self.assertIsNotNone(result["pipe_dn"])


class SpecialSizingPersistenceTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "tmp" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.db_path = temp_root / f"special-sizing-{uuid.uuid4().hex}.db"
        self.previous_db = os.environ.get("SOLAR_CRM_DB")
        os.environ["SOLAR_CRM_DB"] = str(self.db_path)
        init_db(seed=True)

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("SOLAR_CRM_DB", None)
        else:
            os.environ["SOLAR_CRM_DB"] = self.previous_db
        self.db_path.unlink(missing_ok=True)

    def test_special_project_can_be_saved_and_deleted(self):
        result = calculate_energy_system("Híbrido conectado", LOADS, INPUTS)
        project_id = create_special_sizing_project(
            {"name": "Sistema híbrido teste", "system_type": "Híbrido conectado", "loads": LOADS},
            result,
        )
        saved = query_one("SELECT * FROM special_sizing_projects WHERE id=?", (project_id,))
        self.assertTrue(saved["number"].startswith("ESP-"))
        self.assertEqual(saved["system_type"], "Híbrido conectado")

        delete_record("special_sizing_project", project_id)
        self.assertIsNone(query_one("SELECT id FROM special_sizing_projects WHERE id=?", (project_id,)))


if __name__ == "__main__":
    unittest.main()
