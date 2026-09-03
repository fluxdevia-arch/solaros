import unittest
from io import BytesIO

from PIL import Image

from solar_crm.engineering import (
    calculate_complete_project,
    generate_roof_croqui,
    plan_string_lengths,
)


MODULE = {
    "manufacturer": "Fabricante",
    "model": "MOD-585",
    "power_wp": 585.0,
    "voc_v": 52.1,
    "vmp_v": 44.0,
    "isc_a": 14.3,
    "imp_a": 13.3,
    "temp_coeff_voc_pct": -0.25,
    "temp_coeff_pmax_pct": -0.35,
    "max_series_fuse_a": 30.0,
    "width_mm": 1134.0,
    "height_mm": 2278.0,
}

INVERTER = {
    "manufacturer": "Fabricante",
    "model": "INV-6K",
    "nominal_power_kw": 6.0,
    "max_dc_power_kw": 9.0,
    "max_dc_voltage_v": 1000.0,
    "mppt_min_v": 120.0,
    "mppt_max_v": 850.0,
    "mppt_count": 2,
    "strings_per_mppt": 2,
    "max_input_current_mppt_a": 40.0,
    "max_short_circuit_current_mppt_a": 50.0,
    "ac_voltage_v": 230.0,
    "phases": "Monofásico",
    "efficiency_pct": 98.0,
}

INPUTS = {
    "name": "Residência teste",
    "module_count": 12,
    "modules_per_string": 6,
    "layout_rows": 2,
    "layout_columns": 6,
    "roof_azimuth_deg": 0,
    "roof_tilt_deg": 15,
    "minimum_temperature_c": 12,
    "maximum_cell_temperature_c": 70,
    "dc_cable_length_m": 20,
    "ac_cable_length_m": 15,
    "voltage_drop_limit_pct": 1.5,
    "correction_factor": 0.8,
    "has_external_spda": False,
}


class EngineeringTests(unittest.TestCase):
    def test_balanced_string_layout(self):
        lengths, warnings = plan_string_lengths(14, 7, 4, 12)
        self.assertEqual(lengths, [7, 7])
        self.assertFalse(warnings)

    def test_complete_project_sizes_strings_and_protections(self):
        result = calculate_complete_project(MODULE, INVERTER, INPUTS)
        self.assertEqual(result["string_lengths"], [6, 6])
        self.assertEqual(result["string_count"], 2)
        self.assertGreater(result["dc_cable"]["section_mm2"], 0)
        self.assertGreater(result["ac_cable"]["section_mm2"], 0)
        self.assertEqual(result["ac_spd_uc_v"], 275)

    def test_croqui_is_valid_png(self):
        result = calculate_complete_project(MODULE, INVERTER, INPUTS)
        png = generate_roof_croqui(INPUTS, MODULE, INVERTER, result)
        image = Image.open(BytesIO(png))
        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.size, (1600, 1000))


if __name__ == "__main__":
    unittest.main()
