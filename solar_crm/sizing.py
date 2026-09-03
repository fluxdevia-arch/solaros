from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil, floor, pi, sqrt


CABLE_SECTIONS_MM2 = [1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240]
STANDARD_BREAKERS_A = [6, 10, 16, 20, 25, 32, 40, 50, 63, 70, 80, 100, 125, 160, 200, 225, 250, 315, 400]

# Valores conservadores de referência para cobre/PVC 70 °C em eletroduto.
# O usuário deve confirmar método de instalação, agrupamento e temperatura no projeto executivo.
AMPACITY_B1_A = {
    2: [17.5, 24, 32, 41, 57, 76, 101, 125, 151, 192, 232, 269, 309, 353, 415],
    3: [15.5, 21, 28, 36, 50, 68, 89, 110, 134, 171, 207, 239, 275, 314, 370],
}

CONDUIT_OPTIONS = [
    ("DN 20 (3/4\")", 16.4),
    ("DN 25 (1\")", 21.3),
    ("DN 32 (1 1/4\")", 27.5),
    ("DN 40 (1 1/2\")", 36.1),
    ("DN 50 (2\")", 41.4),
    ("DN 60 (2 1/2\")", 52.0),
    ("DN 75 (3\")", 66.0),
    ("DN 100 (4\")", 88.0),
]


@dataclass(frozen=True)
class PvSizing:
    target_energy_kwh: float
    required_kwp: float
    module_count: int
    installed_kwp: float
    estimated_monthly_kwh: float
    inverter_kw: float
    dc_ac_ratio: float
    roof_area_m2: float


@dataclass(frozen=True)
class StringSizing:
    voc_cold_v: float
    vmp_hot_v: float
    max_modules_series: int
    min_modules_series: int
    suggested_modules_series: int
    string_count: int
    strings_per_mppt: int
    operating_vmp_v: float
    cold_open_circuit_v: float
    current_per_mppt_a: float
    valid: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CableSizing:
    design_current_a: float
    required_ampacity_a: float
    section_mm2: float
    reference_ampacity_a: float
    voltage_drop_v: float
    voltage_drop_pct: float
    criterion: str
    protective_conductor_mm2: float
    breaker_a: int | None
    valid: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ConduitSizing:
    occupied_area_mm2: float
    minimum_internal_diameter_mm: float
    recommended_conduit: str
    reference_internal_diameter_mm: float
    occupancy_pct: float
    valid: bool


def size_pv_system(
    monthly_consumption_kwh: float,
    target_offset_pct: float,
    peak_sun_hours: float,
    performance_ratio_pct: float,
    module_power_wp: float,
    inverter_kw: float,
    module_area_m2: float,
) -> PvSizing:
    if min(monthly_consumption_kwh, target_offset_pct, peak_sun_hours, performance_ratio_pct, module_power_wp, inverter_kw, module_area_m2) <= 0:
        raise ValueError("Os valores elétricos e energéticos devem ser maiores que zero.")
    target_energy = monthly_consumption_kwh * target_offset_pct / 100
    required_kwp = target_energy / (30 * peak_sun_hours * performance_ratio_pct / 100)
    module_count = max(1, ceil(required_kwp * 1000 / module_power_wp))
    installed_kwp = module_count * module_power_wp / 1000
    estimated_energy = installed_kwp * peak_sun_hours * 30 * performance_ratio_pct / 100
    return PvSizing(
        target_energy_kwh=target_energy,
        required_kwp=required_kwp,
        module_count=module_count,
        installed_kwp=installed_kwp,
        estimated_monthly_kwh=estimated_energy,
        inverter_kw=inverter_kw,
        dc_ac_ratio=installed_kwp / inverter_kw,
        roof_area_m2=module_count * module_area_m2,
    )


def size_strings(
    module_count: int,
    module_voc_v: float,
    module_vmp_v: float,
    module_isc_a: float,
    voc_temp_coefficient_pct: float,
    vmp_temp_coefficient_pct: float,
    minimum_temperature_c: float,
    maximum_cell_temperature_c: float,
    inverter_max_dc_v: float,
    inverter_mppt_min_v: float,
    inverter_mppt_max_v: float,
    inverter_mppt_count: int,
    inverter_max_current_per_mppt_a: float,
    selected_modules_per_string: int | None = None,
) -> StringSizing:
    positive_values = [
        module_count, module_voc_v, module_vmp_v, module_isc_a, inverter_max_dc_v,
        inverter_mppt_min_v, inverter_mppt_max_v, inverter_mppt_count,
        inverter_max_current_per_mppt_a,
    ]
    if min(positive_values) <= 0:
        raise ValueError("As grandezas do módulo e do inversor devem ser maiores que zero.")

    voc_cold = module_voc_v * (1 + abs(voc_temp_coefficient_pct) / 100 * max(0, 25 - minimum_temperature_c))
    vmp_hot = module_vmp_v * (1 - abs(vmp_temp_coefficient_pct) / 100 * max(0, maximum_cell_temperature_c - 25))
    vmp_cold = module_vmp_v * (1 + abs(vmp_temp_coefficient_pct) / 100 * max(0, 25 - minimum_temperature_c))
    max_series_voltage = floor(inverter_max_dc_v / voc_cold)
    max_series_mppt = floor(inverter_mppt_max_v / vmp_cold)
    max_series = min(max_series_voltage, max_series_mppt)
    min_series = ceil(inverter_mppt_min_v / vmp_hot) if vmp_hot > 0 else 0

    suggested = selected_modules_per_string or max(min_series, min(max_series, round((min_series + max_series) / 2)))
    string_count = ceil(module_count / suggested) if suggested > 0 else 0
    strings_per_mppt = ceil(string_count / inverter_mppt_count) if inverter_mppt_count else 0
    current_per_mppt = strings_per_mppt * module_isc_a * 1.25
    warnings: list[str] = []
    if max_series < min_series:
        warnings.append("Não existe quantidade de módulos em série compatível com esta janela MPPT.")
    if suggested < min_series or suggested > max_series:
        warnings.append(f"A string selecionada deve ficar entre {min_series} e {max_series} módulos.")
    if module_count % suggested != 0:
        warnings.append("A última string ficaria incompleta; redistribua os módulos entre strings equivalentes.")
    if current_per_mppt > inverter_max_current_per_mppt_a:
        warnings.append("A corrente calculada por MPPT supera o limite informado do inversor.")

    return StringSizing(
        voc_cold_v=voc_cold,
        vmp_hot_v=vmp_hot,
        max_modules_series=max_series,
        min_modules_series=min_series,
        suggested_modules_series=suggested,
        string_count=string_count,
        strings_per_mppt=strings_per_mppt,
        operating_vmp_v=suggested * vmp_hot,
        cold_open_circuit_v=suggested * voc_cold,
        current_per_mppt_a=current_per_mppt,
        valid=not warnings,
        warnings=tuple(warnings),
    )


def circuit_current(power_kw: float, voltage_v: float, phases: str, power_factor: float = 1.0, efficiency: float = 1.0) -> float:
    if min(power_kw, voltage_v, power_factor, efficiency) <= 0:
        raise ValueError("Potência, tensão, fator de potência e rendimento devem ser maiores que zero.")
    denominator = voltage_v * power_factor * efficiency
    if phases == "Trifásico":
        denominator *= sqrt(3)
    return power_kw * 1000 / denominator


def next_standard_breaker(current_a: float) -> int | None:
    return next((rating for rating in STANDARD_BREAKERS_A if rating >= current_a), None)


def protective_conductor(section_mm2: float) -> float:
    if section_mm2 <= 16:
        return section_mm2
    if section_mm2 <= 35:
        return 16
    required = section_mm2 / 2
    return next((section for section in CABLE_SECTIONS_MM2 if section >= required), CABLE_SECTIONS_MM2[-1])


def voltage_drop(
    current_a: float,
    voltage_v: float,
    length_m: float,
    section_mm2: float,
    phases: str,
    resistivity_ohm_mm2_m: float = 0.0225,
) -> tuple[float, float]:
    factor = sqrt(3) if phases == "Trifásico" else 2
    drop_v = factor * resistivity_ohm_mm2_m * length_m * current_a / section_mm2
    return drop_v, drop_v / voltage_v * 100


def size_cable(
    operating_current_a: float,
    voltage_v: float,
    length_m: float,
    phases: str,
    voltage_drop_limit_pct: float,
    continuous_factor: float = 1.25,
    correction_factor: float = 1.0,
    loaded_conductors: int | None = None,
) -> CableSizing:
    if min(operating_current_a, voltage_v, voltage_drop_limit_pct, continuous_factor, correction_factor) <= 0:
        raise ValueError("Os dados do circuito e fatores de correção devem ser maiores que zero.")
    if length_m < 0:
        raise ValueError("O comprimento não pode ser negativo.")
    loaded = loaded_conductors or (3 if phases == "Trifásico" else 2)
    if loaded not in AMPACITY_B1_A:
        raise ValueError("Use dois ou três condutores carregados.")

    design_current = operating_current_a * continuous_factor
    required_ampacity = design_current / correction_factor
    selected: tuple[float, float, float, float] | None = None
    ampacity_section: float | None = None
    drop_section: float | None = None
    for section, ampacity in zip(CABLE_SECTIONS_MM2, AMPACITY_B1_A[loaded]):
        drop_v, drop_pct = voltage_drop(operating_current_a, voltage_v, length_m, section, phases)
        if ampacity >= required_ampacity and ampacity_section is None:
            ampacity_section = section
        if drop_pct <= voltage_drop_limit_pct and drop_section is None:
            drop_section = section
        if ampacity >= required_ampacity and drop_pct <= voltage_drop_limit_pct:
            selected = (section, ampacity, drop_v, drop_pct)
            break

    warnings: list[str] = []
    if selected is None:
        section = CABLE_SECTIONS_MM2[-1]
        ampacity = AMPACITY_B1_A[loaded][-1]
        drop_v, drop_pct = voltage_drop(operating_current_a, voltage_v, length_m, section, phases)
        selected = (section, ampacity, drop_v, drop_pct)
        warnings.append("O cálculo ultrapassou a tabela interna; faça o dimensionamento executivo completo.")

    section, ampacity, drop_v, drop_pct = selected
    if ampacity_section is None:
        criterion = "fora da tabela"
    elif drop_section is not None and drop_section > ampacity_section:
        criterion = "queda de tensão"
    else:
        criterion = "capacidade de corrente"

    breaker = next_standard_breaker(design_current)
    if breaker is None:
        warnings.append("Não há disjuntor padronizado na faixa interna para esta corrente.")
    elif breaker > ampacity * correction_factor:
        warnings.append("O disjuntor sugerido não fica abaixo da capacidade corrigida do cabo; aumente a seção ou revise os fatores.")

    return CableSizing(
        design_current_a=design_current,
        required_ampacity_a=required_ampacity,
        section_mm2=section,
        reference_ampacity_a=ampacity,
        voltage_drop_v=drop_v,
        voltage_drop_pct=drop_pct,
        criterion=criterion,
        protective_conductor_mm2=protective_conductor(section),
        breaker_a=breaker,
        valid=not warnings,
        warnings=tuple(warnings),
    )


def size_conduit(cables: list[tuple[int, float]], maximum_fill_pct: float = 40) -> ConduitSizing:
    if not cables or not 0 < maximum_fill_pct < 100:
        raise ValueError("Informe os cabos e uma taxa de ocupação entre 0% e 100%.")
    if any(quantity <= 0 or diameter <= 0 for quantity, diameter in cables):
        raise ValueError("Quantidade e diâmetro externo dos cabos devem ser maiores que zero.")
    occupied = sum(quantity * pi * diameter**2 / 4 for quantity, diameter in cables)
    minimum_diameter = sqrt(4 * occupied / (pi * maximum_fill_pct / 100))
    option = next(((name, diameter) for name, diameter in CONDUIT_OPTIONS if diameter >= minimum_diameter), None)
    if option is None:
        name, reference_diameter = "Acima de DN 100 — calcular pelo fabricante", CONDUIT_OPTIONS[-1][1]
        valid = False
    else:
        name, reference_diameter = option
        valid = True
    occupancy = occupied / (pi * reference_diameter**2 / 4) * 100
    return ConduitSizing(occupied, minimum_diameter, name, reference_diameter, occupancy, valid)


ENERGISA_PB_MONO_230 = [
    {"category": "M1", "min": 0, "max": 6.9, "criterion": "Carga instalada", "connection_al": 10, "entry_pvc_cu": 6, "entry_xlpe_cu": 6, "ground_cu": "6", "breaker": "30/32 A", "conduit": '3/4"', "box": "CMI-01"},
    {"category": "M2", "min": 6.9, "max": 9.2, "criterion": "Carga instalada", "connection_al": 10, "entry_pvc_cu": 10, "entry_xlpe_cu": 6, "ground_cu": "6 ou 10¹", "breaker": "40 A", "conduit": '3/4"', "box": "CMI-01"},
    {"category": "M3", "min": 9.2, "max": 11.5, "criterion": "Carga instalada", "connection_al": 10, "entry_pvc_cu": 10, "entry_xlpe_cu": 6, "ground_cu": "6 ou 10¹", "breaker": "50 A", "conduit": '1"', "box": "CMI-01"},
    {"category": "M4", "min": 11.5, "max": 15.0, "criterion": "Carga instalada", "connection_al": 16, "entry_pvc_cu": 16, "entry_xlpe_cu": 10, "ground_cu": "10 ou 16¹", "breaker": "70 A", "conduit": '1"', "box": "CMI-01"},
    {"category": "M5", "min": 15.0, "max": 23.0, "criterion": "Carga instalada", "connection_al": 35, "entry_pvc_cu": 35, "entry_xlpe_cu": 25, "ground_cu": "16", "breaker": "100 A", "conduit": '1 1/4"', "box": "CMI-01"},
]

ENERGISA_PB_THREE_380_220 = [
    {"category": "T1", "min": 0, "max": 26.1, "criterion": "Demanda", "connection_al": 10, "entry_pvc_cu": 10, "entry_xlpe_cu": 6, "ground_cu": "6 ou 10²", "breaker": "40 A", "conduit": '3/4"', "box": "CMI-02 / CMI-03"},
    {"category": "T2", "min": 26.1, "max": 35.4, "criterion": "Demanda", "connection_al": 16, "entry_pvc_cu": 16, "entry_xlpe_cu": 10, "ground_cu": "10 ou 16²", "breaker": "50 A", "conduit": '1"', "box": "CMI-02 / CMI-03"},
    {"category": "T3", "min": 35.4, "max": 46.1, "criterion": "Demanda", "connection_al": 25, "entry_pvc_cu": 25, "entry_xlpe_cu": "16 (25)¹", "ground_cu": "16", "breaker": "70 A", "conduit": '1 1/4"', "box": "CMI-02 / CMI-03"},
    {"category": "T4", "min": 46.1, "max": 65.8, "criterion": "Demanda", "connection_al": 35, "entry_pvc_cu": 50, "entry_xlpe_cu": 35, "ground_cu": "25", "breaker": "100 A", "conduit": '1 1/2"', "box": "CMI-02 / CMI-03"},
    {"category": "T5", "min": 65.8, "max": 81.5, "criterion": "Demanda", "connection_al": 70, "entry_pvc_cu": 70, "entry_xlpe_cu": "50 (70)¹", "ground_cu": "25 (35)¹", "breaker": "125 A", "conduit": '2"', "box": "CMD-BT 200"},
]


def energisa_pb_service_category(connection: str, value: float) -> dict | None:
    rows = ENERGISA_PB_MONO_230 if connection == "Monofásico 230 V" else ENERGISA_PB_THREE_380_220
    return next((row for row in rows if row["min"] < value <= row["max"]), None)


def result_as_dict(result: object) -> dict:
    return asdict(result)
