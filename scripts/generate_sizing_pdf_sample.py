from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from solar_crm.db import init_db
from solar_crm.sizing_documents import generate_special_sizing_pdf
from solar_crm.special_sizing import calculate_energy_system


os.environ["SOLAR_CRM_DB"] = str(ROOT / "tmp" / "sizing-pdf-sample.db")
init_db(seed=True)

loads = [
    {"Equipamento": "Geladeira", "Quantidade": 1, "Potência unitária (W)": 250, "Horas/dia": 10, "Simultaneidade (%)": 60, "Prioritária": True, "Autonomia (h)": 8, "Pico de partida (x)": 3},
    {"Equipamento": "Iluminação", "Quantidade": 12, "Potência unitária (W)": 12, "Horas/dia": 5, "Simultaneidade (%)": 100, "Prioritária": True, "Autonomia (h)": 6, "Pico de partida (x)": 1},
    {"Equipamento": "Ar-condicionado", "Quantidade": 1, "Potência unitária (W)": 1200, "Horas/dia": 6, "Simultaneidade (%)": 100, "Prioritária": False, "Autonomia (h)": 0, "Pico de partida (x)": 2.5},
]
inputs = {
    "monthly_bill_kwh": 450, "solar_coverage_pct": 100, "peak_sun_hours": 5.4, "performance_ratio_pct": 75,
    "module_power_wp": 585, "module_voc_v": 52.1, "module_vmp_v": 44, "module_isc_a": 14.3,
    "module_voc_coeff_pct": -0.25, "module_vmp_coeff_pct": -0.35, "minimum_temperature_c": 12,
    "maximum_cell_temperature_c": 70, "inverter_max_dc_voltage_v": 600, "inverter_mppt_min_v": 120,
    "inverter_mppt_max_v": 550, "inverter_mppt_count": 2, "inverter_max_current_mppt_a": 32,
    "modules_per_string": 6, "inverter_efficiency_pct": 95, "phases": "Monofásico", "ac_voltage_v": 230,
    "power_factor": 0.92, "design_margin_pct": 20, "battery_bank_voltage_v": 48,
    "battery_unit_voltage_v": 51.2, "battery_unit_ah": 100, "battery_dod_pct": 80,
    "battery_efficiency_pct": 92, "autonomy_days": 1, "battery_reserve_pct": 15,
    "dc_cable_length_m": 20, "battery_cable_length_m": 2, "ac_cable_length_m": 15,
    "voltage_drop_limit_pct": 2, "correction_factor": 0.8,
}

result = calculate_energy_system("Híbrido conectado", loads, inputs)
generate_special_sizing_pdf(
    {
        "name": "Sistema híbrido residencial",
        "client_name": "Cliente demonstração",
        "address": "João Pessoa/PB",
        "status": "Pré-dimensionamento",
        "phases": "Monofásico",
        "ac_voltage_v": 230,
    },
    result,
    ROOT / "output" / "pdf" / "Modelo_Dimensionamento_Hibrido_SolarOS.pdf",
)
