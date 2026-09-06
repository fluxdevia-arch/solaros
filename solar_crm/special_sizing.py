from __future__ import annotations

from math import ceil, isfinite, pi, sqrt
from typing import Any

from solar_crm.sizing import next_standard_breaker, size_cable, size_strings


SYSTEM_TYPES = ["Híbrido conectado", "Zero grid", "Off-grid", "Bombeamento solar"]
BATTERY_CHEMISTRIES = {
    "LiFePO4": {"dod_pct": 80.0, "efficiency_pct": 92.0},
    "Lítio NMC": {"dod_pct": 80.0, "efficiency_pct": 90.0},
    "Chumbo estacionária": {"dod_pct": 50.0, "efficiency_pct": 82.0},
}
DC_PROTECTION_A = [10, 12, 15, 16, 20, 25, 30, 32, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630]
DC_SPD_V = [150, 275, 320, 440, 600, 800, 1000, 1200, 1500]
PIPE_DN_MM = [20, 25, 32, 40, 50, 60, 75, 85, 100, 125, 150, 200]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _next(value: float, options: list[int]) -> int | None:
    return next((item for item in options if item >= value), None)


def _phase_for_cable(phases: str) -> str:
    return "Trifásico" if phases == "Trifásico" else "Monofásico"


def normalize_loads(rows: list[dict]) -> list[dict]:
    loads: list[dict] = []
    for row in rows:
        name = str(row.get("Equipamento") or "").strip()
        quantity = int(_number(row.get("Quantidade"), 0))
        power_w = _number(row.get("Potência unitária (W)"), 0)
        if not name and quantity == 0 and power_w == 0:
            continue
        if not name or quantity <= 0 or power_w <= 0:
            raise ValueError("Cada carga deve ter equipamento, quantidade e potência maiores que zero.")
        daily_hours = _number(row.get("Horas/dia"), 0)
        simultaneity = _number(row.get("Simultaneidade (%)"), 100)
        backup_hours = _number(row.get("Autonomia (h)"), 0)
        surge = _number(row.get("Pico de partida (x)"), 1)
        if daily_hours < 0 or backup_hours < 0 or not 0 < simultaneity <= 100 or surge < 1:
            raise ValueError("Revise horas, simultaneidade e pico de partida das cargas.")
        loads.append({
            "name": name,
            "quantity": quantity,
            "power_w": power_w,
            "daily_hours": daily_hours,
            "simultaneity_pct": simultaneity,
            "priority": bool(row.get("Prioritária")),
            "backup_hours": backup_hours,
            "surge_multiplier": surge,
        })
    if not loads:
        raise ValueError("Cadastre pelo menos uma carga para dimensionar o sistema.")
    return loads


def calculate_energy_system(system_type: str, loads: list[dict], inputs: dict) -> dict:
    if system_type not in SYSTEM_TYPES[:3]:
        raise ValueError("Modalidade elétrica inválida.")
    normalized = normalize_loads(loads)
    monthly_bill_kwh = _number(inputs.get("monthly_bill_kwh"))
    coverage_pct = _number(inputs.get("solar_coverage_pct"), 100)
    psh = _number(inputs.get("peak_sun_hours"), 5.4)
    performance_ratio = _number(inputs.get("performance_ratio_pct"), 75) / 100
    module_power_wp = _number(inputs.get("module_power_wp"), 585)
    phase_voltage = _number(inputs.get("ac_voltage_v"), 230)
    phases = str(inputs.get("phases") or "Monofásico")
    power_factor = _number(inputs.get("power_factor"), 0.92)
    inverter_efficiency = _number(inputs.get("inverter_efficiency_pct"), 95) / 100
    design_margin = 1 + _number(inputs.get("design_margin_pct"), 20) / 100
    if min(coverage_pct, psh, performance_ratio, module_power_wp, phase_voltage, power_factor, inverter_efficiency) <= 0:
        raise ValueError("Os parâmetros energéticos e elétricos devem ser maiores que zero.")

    daily_load_kwh = sum(
        row["quantity"] * row["power_w"] * row["daily_hours"] * row["simultaneity_pct"] / 100 / 1000
        for row in normalized
    )
    bill_daily_kwh = monthly_bill_kwh / 30 if monthly_bill_kwh > 0 else 0
    reference_daily_kwh = max(daily_load_kwh, bill_daily_kwh)
    solar_target_kwh_day = reference_daily_kwh * coverage_pct / 100
    required_pv_kwp = solar_target_kwh_day / (psh * performance_ratio)
    module_count = max(1, ceil(required_pv_kwp * 1000 / module_power_wp))
    installed_pv_kwp = module_count * module_power_wp / 1000
    estimated_generation_kwh_month = installed_pv_kwp * psh * performance_ratio * 30

    backup_rows = normalized if system_type == "Off-grid" else [row for row in normalized if row["priority"]]
    if not backup_rows and system_type != "Zero grid":
        raise ValueError("Marque pelo menos uma carga prioritária ou informe as cargas do sistema off-grid.")
    backup_energy_kwh = sum(
        row["quantity"] * row["power_w"] * row["backup_hours"] * row["simultaneity_pct"] / 100 / 1000
        for row in backup_rows
    )
    autonomy_days = _number(inputs.get("autonomy_days"), 1)
    battery_required = system_type != "Zero grid" or bool(inputs.get("include_battery"))
    if not battery_required:
        backup_energy_kwh = 0.0
    dod = _number(inputs.get("battery_dod_pct"), 80) / 100
    battery_efficiency = _number(inputs.get("battery_efficiency_pct"), 92) / 100
    bank_voltage = _number(inputs.get("battery_bank_voltage_v"), 48)
    battery_unit_voltage = _number(inputs.get("battery_unit_voltage_v"), 51.2)
    battery_unit_ah = _number(inputs.get("battery_unit_ah"), 100)
    reserve_factor = 1 + _number(inputs.get("battery_reserve_pct"), 15) / 100
    nominal_battery_kwh = 0.0
    battery_series = 0
    battery_parallel = 0
    battery_units = 0
    installed_battery_kwh = 0.0
    if battery_required:
        if backup_energy_kwh <= 0:
            raise ValueError("Informe a autonomia em horas das cargas que serão alimentadas pelas baterias.")
        if min(dod, battery_efficiency, bank_voltage, battery_unit_voltage, battery_unit_ah, autonomy_days) <= 0:
            raise ValueError("Revise tensão, capacidade, eficiência, profundidade de descarga e autonomia das baterias.")
        nominal_battery_kwh = backup_energy_kwh * autonomy_days * reserve_factor / (dod * battery_efficiency)
        battery_series = max(1, ceil(bank_voltage / battery_unit_voltage))
        string_energy_kwh = battery_series * battery_unit_voltage * battery_unit_ah / 1000
        battery_parallel = max(1, ceil(nominal_battery_kwh / string_energy_kwh))
        battery_units = battery_series * battery_parallel
        installed_battery_kwh = battery_units * battery_unit_voltage * battery_unit_ah / 1000

    peak_load_kw = sum(
        row["quantity"] * row["power_w"] * row["simultaneity_pct"] / 100 / 1000
        for row in normalized
    )
    backed_peak_kw = sum(
        row["quantity"] * row["power_w"] * row["simultaneity_pct"] / 100 / 1000
        for row in backup_rows
    )
    if system_type == "Zero grid" and not backup_rows:
        backed_peak_kw = peak_load_kw
    largest_start_increment_kw = max(
        (
            row["quantity"] * row["power_w"] * (row["surge_multiplier"] - 1) / 1000
            for row in (backup_rows or normalized)
        ),
        default=0,
    )
    surge_power_kw = backed_peak_kw + largest_start_increment_kw
    inverter_continuous_kw = max(
        backed_peak_kw * design_margin / inverter_efficiency,
        installed_pv_kwp / 1.35,
    )
    inverter_surge_kw = max(surge_power_kw * design_margin, inverter_continuous_kw)

    cable_phase = _phase_for_cable(phases)
    ac_current = inverter_continuous_kw * 1000 / (phase_voltage * power_factor * (sqrt(3) if cable_phase == "Trifásico" else 1))
    ac_cable = size_cable(
        ac_current,
        phase_voltage,
        _number(inputs.get("ac_cable_length_m"), 15),
        cable_phase,
        _number(inputs.get("voltage_drop_limit_pct"), 2),
        1.25,
        _number(inputs.get("correction_factor"), 0.8),
        3 if cable_phase == "Trifásico" else 2,
    )

    module_voc = _number(inputs.get("module_voc_v"), 52.1)
    module_vmp = _number(inputs.get("module_vmp_v"), 44)
    module_isc = _number(inputs.get("module_isc_a"), 14.3)
    string_result = size_strings(
        module_count,
        module_voc,
        module_vmp,
        module_isc,
        _number(inputs.get("module_voc_coeff_pct"), -0.25),
        _number(inputs.get("module_vmp_coeff_pct"), -0.35),
        _number(inputs.get("minimum_temperature_c"), 12),
        _number(inputs.get("maximum_cell_temperature_c"), 70),
        _number(inputs.get("inverter_max_dc_voltage_v"), 600),
        _number(inputs.get("inverter_mppt_min_v"), 120),
        _number(inputs.get("inverter_mppt_max_v"), 550),
        int(_number(inputs.get("inverter_mppt_count"), 2)),
        _number(inputs.get("inverter_max_current_mppt_a"), 32),
        int(_number(inputs.get("modules_per_string"), min(module_count, 8))),
    )
    dc_cable = size_cable(
        module_isc,
        max(string_result.operating_vmp_v, 1),
        _number(inputs.get("dc_cable_length_m"), 20),
        "CC",
        _number(inputs.get("voltage_drop_limit_pct"), 2),
        1.25,
        _number(inputs.get("correction_factor"), 0.8),
        2,
    )

    battery_current_a = inverter_continuous_kw * 1000 / (bank_voltage * inverter_efficiency) if battery_required else 0
    battery_cable = None
    if battery_required:
        battery_cable = size_cable(
            battery_current_a,
            bank_voltage,
            _number(inputs.get("battery_cable_length_m"), 2),
            "CC",
            1.0,
            1.25,
            _number(inputs.get("correction_factor"), 0.8),
            2,
        )

    dc_fuse = _next(1.56 * module_isc, DC_PROTECTION_A)
    dc_switch = _next(1.25 * module_isc * string_result.strings_per_mppt, DC_PROTECTION_A)
    dc_spd = _next(1.2 * string_result.cold_open_circuit_v, DC_SPD_V)
    battery_breaker = _next(1.25 * battery_current_a, DC_PROTECTION_A) if battery_required else None
    has_spda = bool(inputs.get("has_external_spda"))
    ac_spd_voltage = 460 if cable_phase == "Trifásico" else 275
    ac_spd_type = "Tipo 1+2" if has_spda else "Tipo 2"

    warnings = list(string_result.warnings) + list(dc_cable.warnings) + list(ac_cable.warnings)
    if battery_cable:
        warnings.extend(battery_cable.warnings)
    if monthly_bill_kwh and daily_load_kwh and abs(bill_daily_kwh - daily_load_kwh) / max(bill_daily_kwh, daily_load_kwh) > 0.25:
        warnings.append("A energia calculada pelas cargas difere mais de 25% da média da fatura; revise hábitos, sazonalidade e cargas não cadastradas.")
    if battery_required and battery_unit_voltage > bank_voltage * 1.1:
        warnings.append("A tensão unitária da bateria supera a tensão nominal do banco; confirme a faixa do inversor e do BMS.")
    if battery_required and abs(battery_series * battery_unit_voltage - bank_voltage) / bank_voltage > 0.10:
        warnings.append("A associação em série não coincide com a tensão nominal do banco; selecione bateria e inversor compatíveis.")
    if dc_spd is None or dc_spd > _number(inputs.get("inverter_max_dc_voltage_v"), 600):
        warnings.append("Confirme o DPS CC: a tensão calculada não ficou compatível com a tensão máxima informada do inversor.")
    if system_type == "Zero grid":
        warnings.append("Zero grid exige controlador de exportação, TCs corretamente orientados, ensaio de rejeição de carga e processo de conexão conforme a NDU 013 vigente.")
    if system_type == "Off-grid":
        warnings.append("Em sistema isolado, valide o pior mês solar e considere fonte auxiliar para períodos prolongados sem geração.")

    components = [
        {"Grupo": "Geração", "Item": "Módulos fotovoltaicos", "Especificação preliminar": f"{module_count} x {module_power_wp:.0f} Wp = {installed_pv_kwp:.3f} kWp"},
        {"Grupo": "Conversão", "Item": "Inversor", "Especificação preliminar": f">= {inverter_continuous_kw:.2f} kW contínuos; pico >= {inverter_surge_kw:.2f} kW; {phases} {phase_voltage:.0f} V"},
        {"Grupo": "Arranjo CC", "Item": "Strings", "Especificação preliminar": f"{string_result.string_count} strings; {string_result.suggested_modules_series} módulos/string; {string_result.strings_per_mppt} string(s)/MPPT"},
        {"Grupo": "Arranjo CC", "Item": "Cabo solar", "Especificação preliminar": f"{dc_cable.section_mm2:.1f} mm²; queda {dc_cable.voltage_drop_pct:.2f}%"},
        {"Grupo": "Proteção CC", "Item": "Fusível gPV / seccionador / DPS", "Especificação preliminar": f"gPV {dc_fuse or '-'} A; seccionador {dc_switch or '-'} A; DPS {'Tipo 1+2' if has_spda else 'Tipo 2'} Ucpv {dc_spd or '-'} V"},
        {"Grupo": "Saída CA", "Item": "Cabo / disjuntor / DPS", "Especificação preliminar": f"{ac_cable.section_mm2:.1f} mm²; disjuntor {ac_cable.breaker_a or '-'} A; DPS {ac_spd_type} Uc {ac_spd_voltage} V"},
        {"Grupo": "Segurança", "Item": "Aterramento e equipotencialização", "Especificação preliminar": f"PE preliminar {ac_cable.protective_conductor_mm2:.1f} mm²; validar SPDA, eletrodos e medição"},
    ]
    if battery_required:
        components.extend([
            {"Grupo": "Armazenamento", "Item": "Banco de baterias", "Especificação preliminar": f"{battery_units} unidade(s), {battery_series}S x {battery_parallel}P; {installed_battery_kwh:.2f} kWh nominais"},
            {"Grupo": "Armazenamento", "Item": "Cabo e proteção da bateria", "Especificação preliminar": f"{battery_cable.section_mm2:.1f} mm²; proteção CC {battery_breaker or 'fora da faixa'} A; corrente {battery_current_a:.1f} A"},
            {"Grupo": "Armazenamento", "Item": "BMS / desconexão", "Especificação preliminar": "BMS compatível, chave-seccionadora CC, fusível/disjuntor por string e proteção contra curto-circuito"},
        ])
    if system_type == "Híbrido conectado":
        components.append({"Grupo": "Transferência", "Item": "Quadro de cargas prioritárias", "Especificação preliminar": "Saída backup/EPS segregada, intertravamento, bypass e comutação de neutro conforme topologia"})
    if system_type == "Zero grid":
        components.append({"Grupo": "Controle", "Item": "Controlador zero exportação", "Especificação preliminar": "Medidor/controlador, TCs por fase, comunicação fail-safe e resposta inicial <= 1 s"})

    return {
        "system_type": system_type,
        "daily_load_kwh": daily_load_kwh,
        "reference_daily_kwh": reference_daily_kwh,
        "solar_target_kwh_day": solar_target_kwh_day,
        "required_pv_kwp": required_pv_kwp,
        "module_count": module_count,
        "installed_pv_kwp": installed_pv_kwp,
        "estimated_generation_kwh_month": estimated_generation_kwh_month,
        "peak_load_kw": peak_load_kw,
        "backed_peak_kw": backed_peak_kw,
        "surge_power_kw": surge_power_kw,
        "inverter_continuous_kw": inverter_continuous_kw,
        "inverter_surge_kw": inverter_surge_kw,
        "backup_energy_kwh": backup_energy_kwh,
        "nominal_battery_kwh": nominal_battery_kwh,
        "installed_battery_kwh": installed_battery_kwh,
        "battery_units": battery_units,
        "battery_series": battery_series,
        "battery_parallel": battery_parallel,
        "battery_current_a": battery_current_a,
        "string_sizing": string_result.__dict__,
        "dc_cable": dc_cable.__dict__,
        "ac_cable": ac_cable.__dict__,
        "battery_cable": battery_cable.__dict__ if battery_cable else None,
        "components": components,
        "loads": normalized,
        "warnings": tuple(dict.fromkeys(warnings)),
    }


def calculate_solar_pumping(inputs: dict) -> dict:
    daily_volume_m3 = _number(inputs.get("daily_volume_m3"))
    total_head_m = _number(inputs.get("total_head_m"))
    pumping_hours = _number(inputs.get("pumping_hours_day"), 6)
    pump_efficiency = _number(inputs.get("pump_efficiency_pct"), 55) / 100
    drive_efficiency = _number(inputs.get("drive_efficiency_pct"), 92) / 100
    psh = _number(inputs.get("peak_sun_hours"), 5.4)
    solar_derating = _number(inputs.get("solar_derating_pct"), 75) / 100
    module_power_wp = _number(inputs.get("module_power_wp"), 585)
    velocity = _number(inputs.get("pipe_velocity_m_s"), 1.5)
    storage_days = _number(inputs.get("water_storage_days"), 2)
    if min(daily_volume_m3, total_head_m, pumping_hours, pump_efficiency, drive_efficiency, psh, solar_derating, module_power_wp, velocity) <= 0:
        raise ValueError("Os dados hidráulicos, solares e elétricos devem ser maiores que zero.")
    flow_m3_h = daily_volume_m3 / pumping_hours
    flow_m3_s = flow_m3_h / 3600
    hydraulic_kw = 1000 * 9.80665 * flow_m3_s * total_head_m / 1000
    pump_input_kw = hydraulic_kw / pump_efficiency
    daily_energy_kwh = pump_input_kw * pumping_hours / drive_efficiency
    required_pv_kwp = daily_energy_kwh / (psh * solar_derating)
    module_count = max(1, ceil(required_pv_kwp * 1000 / module_power_wp))
    installed_pv_kwp = module_count * module_power_wp / 1000
    drive_kw = pump_input_kw * 1.25
    pipe_internal_mm = sqrt(4 * flow_m3_s / (pi * velocity)) * 1000
    pipe_dn = _next(pipe_internal_mm, PIPE_DN_MM)
    reservoir_m3 = daily_volume_m3 * storage_days
    phases = str(inputs.get("phases") or "Trifásico")
    voltage = _number(inputs.get("ac_voltage_v"), 380)
    pf = _number(inputs.get("power_factor"), 0.85)
    current = drive_kw * 1000 / (voltage * pf * (sqrt(3) if phases == "Trifásico" else 1))
    cable = size_cable(
        current,
        voltage,
        _number(inputs.get("cable_length_m"), 50),
        _phase_for_cable(phases),
        _number(inputs.get("voltage_drop_limit_pct"), 3),
        1.25,
        _number(inputs.get("correction_factor"), 0.8),
        3 if phases == "Trifásico" else 2,
    )
    module_voc = _number(inputs.get("module_voc_v"), 52.1)
    module_vmp = _number(inputs.get("module_vmp_v"), 44)
    module_isc = _number(inputs.get("module_isc_a"), 14.3)
    string_result = size_strings(
        module_count,
        module_voc,
        module_vmp,
        module_isc,
        _number(inputs.get("module_voc_coeff_pct"), -0.25),
        _number(inputs.get("module_vmp_coeff_pct"), -0.35),
        _number(inputs.get("minimum_temperature_c"), 12),
        _number(inputs.get("maximum_cell_temperature_c"), 70),
        _number(inputs.get("controller_max_dc_voltage_v"), 600),
        _number(inputs.get("controller_mppt_min_v"), 120),
        _number(inputs.get("controller_mppt_max_v"), 550),
        int(_number(inputs.get("controller_mppt_count"), 1)),
        _number(inputs.get("controller_max_current_mppt_a"), 32),
        int(_number(inputs.get("modules_per_string"), min(module_count, 6))),
    )
    dc_cable = size_cable(
        module_isc,
        max(string_result.operating_vmp_v, 1),
        _number(inputs.get("pv_cable_length_m"), 20),
        "CC",
        _number(inputs.get("voltage_drop_limit_pct"), 3),
        1.25,
        _number(inputs.get("correction_factor"), 0.8),
        2,
    )
    dc_fuse = _next(1.56 * module_isc, DC_PROTECTION_A)
    dc_switch = _next(1.25 * module_isc * string_result.strings_per_mppt, DC_PROTECTION_A)
    dc_spd = _next(1.2 * string_result.cold_open_circuit_v, DC_SPD_V)
    warnings = list(cable.warnings) + list(string_result.warnings) + list(dc_cable.warnings)
    warnings.extend([
        "A altura manométrica total deve incluir desnível, perdas na tubulação, conexões, filtros e pressão residual requerida.",
        "Confirme a curva vazão x altura da bomba e a faixa MPPT do controlador no pior cenário de irradiância e temperatura.",
    ])
    components = [
        {"Grupo": "Hidráulica", "Item": "Bomba", "Especificação preliminar": f">= {pump_input_kw:.2f} kW no ponto {flow_m3_h:.2f} m³/h x {total_head_m:.1f} mca"},
        {"Grupo": "Hidráulica", "Item": "Tubulação", "Especificação preliminar": f"Diâmetro interno calculado {pipe_internal_mm:.1f} mm; referência DN {pipe_dn or '> 200'}; recalcular perdas"},
        {"Grupo": "Hidráulica", "Item": "Reservatório", "Especificação preliminar": f">= {reservoir_m3:.1f} m³ para {storage_days:.1f} dia(s)"},
        {"Grupo": "Geração", "Item": "Módulos fotovoltaicos", "Especificação preliminar": f"{module_count} x {module_power_wp:.0f} Wp = {installed_pv_kwp:.3f} kWp"},
        {"Grupo": "Arranjo CC", "Item": "Strings e cabo solar", "Especificação preliminar": f"{string_result.string_count} strings, {string_result.suggested_modules_series} módulos/string; cabo {dc_cable.section_mm2:.1f} mm²"},
        {"Grupo": "Proteção CC", "Item": "Fusível / seccionador / DPS", "Especificação preliminar": f"gPV {dc_fuse or '-'} A; seccionador {dc_switch or '-'} A; DPS Tipo 2 Ucpv {dc_spd or '-'} V"},
        {"Grupo": "Controle", "Item": "Inversor/controlador de bombeamento", "Especificação preliminar": f">= {drive_kw:.2f} kW, MPPT solar, partida suave, proteção contra poço seco e nível"},
        {"Grupo": "Saída do controlador", "Item": "Cabo / proteção", "Especificação preliminar": f"{cable.section_mm2:.1f} mm²; disjuntor {cable.breaker_a or '-'} A; queda {cable.voltage_drop_pct:.2f}%"},
        {"Grupo": "Sensores", "Item": "Comando e proteção", "Especificação preliminar": "Boias/sondas de nível, sensor de poço seco, transdutor se necessário, aterramento e DPS"},
    ]
    return {
        "system_type": "Bombeamento solar",
        "flow_m3_h": flow_m3_h,
        "hydraulic_power_kw": hydraulic_kw,
        "pump_input_kw": pump_input_kw,
        "daily_energy_kwh": daily_energy_kwh,
        "required_pv_kwp": required_pv_kwp,
        "module_count": module_count,
        "installed_pv_kwp": installed_pv_kwp,
        "drive_kw": drive_kw,
        "pipe_internal_mm": pipe_internal_mm,
        "pipe_dn": pipe_dn,
        "reservoir_m3": reservoir_m3,
        "string_sizing": string_result.__dict__,
        "dc_cable": dc_cable.__dict__,
        "cable": cable.__dict__,
        "components": components,
        "warnings": tuple(dict.fromkeys(warnings)),
    }


def build_special_memorial(project: dict, result: dict) -> str:
    lines = [
        f"# SolarOS — pré-dimensionamento {result['system_type']}",
        "",
        f"**Projeto:** {project.get('name') or 'Sem identificação'}  ",
        f"**Cliente:** {project.get('client_name') or 'Não vinculado'}  ",
        f"**Endereço:** {project.get('address') or '-'}",
        "",
        "> Resultado preliminar. A seleção final depende dos datasheets, curvas dos equipamentos, estudo do local, normas aplicáveis, projeto executivo e responsabilidade técnica.",
        "",
        "## Resumo",
    ]
    if result["system_type"] == "Bombeamento solar":
        lines.extend([
            f"- Vazão de projeto: {result['flow_m3_h']:.2f} m³/h",
            f"- Bomba: {result['pump_input_kw']:.2f} kW",
            f"- Arranjo FV: {result['module_count']} módulos / {result['installed_pv_kwp']:.3f} kWp",
            f"- Controlador: mínimo {result['drive_kw']:.2f} kW",
            f"- Tubulação: diâmetro interno calculado {result['pipe_internal_mm']:.1f} mm",
            f"- Reservação: {result['reservoir_m3']:.1f} m³",
        ])
    else:
        lines.extend([
            f"- Consumo calculado: {result['daily_load_kwh']:.2f} kWh/dia",
            f"- Arranjo FV: {result['module_count']} módulos / {result['installed_pv_kwp']:.3f} kWp",
            f"- Inversor: mínimo {result['inverter_continuous_kw']:.2f} kW contínuos e {result['inverter_surge_kw']:.2f} kW de pico",
            f"- Energia de backup: {result['backup_energy_kwh']:.2f} kWh",
            f"- Banco instalado: {result['installed_battery_kwh']:.2f} kWh / {result['battery_units']} unidade(s)",
        ])
    lines.extend(["", "## Lista técnica preliminar"])
    for item in result["components"]:
        lines.append(f"- **{item['Grupo']} — {item['Item']}:** {item['Especificação preliminar']}")
    lines.extend(["", "## Alertas e validações"])
    for warning in result["warnings"]:
        lines.append(f"- {warning}")
    lines.extend([
        "", "## Verificações executivas obrigatórias",
        "- Confirmar corrente de curto-circuito, capacidade de interrupção, seletividade, método de instalação, agrupamento e temperatura.",
        "- Conferir compatibilidade elétrica e de comunicação entre módulos, inversor/controlador, baterias e BMS.",
        "- Validar aterramento, equipotencialização, SPDA, DR quando aplicável, seccionamento e sinalização.",
        "- Para sistemas conectados, seguir o processo e a norma vigente da distribuidora antes da energização.",
    ])
    return "\n".join(lines)
