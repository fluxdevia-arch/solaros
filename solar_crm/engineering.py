from __future__ import annotations

import re
from dataclasses import asdict
from io import BytesIO
from math import ceil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from solar_crm.sizing import circuit_current, size_cable, size_strings


DC_PROTECTION_A = [10, 12, 15, 16, 20, 25, 30, 32, 40, 50, 63, 80, 100, 125]
DC_SPD_V = [150, 300, 600, 800, 1000, 1200, 1500]
STRING_COLORS = [
    "#0B6E4F", "#E67E22", "#2667FF", "#9C27B0", "#C62828", "#00838F",
    "#6D4C41", "#7CB342", "#3949AB", "#F4511E", "#546E7A", "#AD1457",
]


def _next_standard(value: float, options: list[int]) -> int | None:
    return next((option for option in options if option >= value), None)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def plan_string_lengths(
    module_count: int,
    preferred_modules: int,
    minimum_modules: int,
    maximum_modules: int,
) -> tuple[list[int], tuple[str, ...]]:
    """Distribute modules across electrically valid, near-equal strings."""
    if min(module_count, preferred_modules) <= 0:
        raise ValueError("Informe uma quantidade de módulos e módulos por string maior que zero.")
    warnings: list[str] = []
    if minimum_modules <= 0 or maximum_modules < minimum_modules:
        return [module_count], ("A janela MPPT informada não permite formar strings válidas.",)

    minimum_strings = max(1, ceil(module_count / maximum_modules))
    maximum_strings = max(1, module_count // minimum_modules)
    candidates: list[tuple[float, int, list[int]]] = []
    for string_count in range(minimum_strings, maximum_strings + 1):
        base, remainder = divmod(module_count, string_count)
        lengths = [base + (1 if index < remainder else 0) for index in range(string_count)]
        if min(lengths) >= minimum_modules and max(lengths) <= maximum_modules:
            candidates.append((abs(module_count / string_count - preferred_modules), string_count, lengths))

    if not candidates:
        fallback_count = max(1, ceil(module_count / preferred_modules))
        base, remainder = divmod(module_count, fallback_count)
        lengths = [base + (1 if index < remainder else 0) for index in range(fallback_count)]
        warnings.append("Não foi possível distribuir todos os módulos dentro da janela MPPT; revise a quantidade ou o inversor.")
        return lengths, tuple(warnings)

    _, _, selected = min(candidates, key=lambda item: (item[0], item[1]))
    if len(set(selected)) > 1:
        warnings.append("As strings ficaram com quantidades diferentes; mantenha strings desiguais em MPPTs independentes.")
    return selected, tuple(warnings)


def assign_strings_to_mppts(string_lengths: list[int], mppt_count: int) -> list[dict[str, int]]:
    if mppt_count <= 0:
        raise ValueError("O inversor deve possuir pelo menos um MPPT.")
    loads = [0] * mppt_count
    assignments: list[dict[str, int]] = []
    for index, length in enumerate(sorted(string_lengths, reverse=True), start=1):
        target = min(range(mppt_count), key=lambda position: loads[position])
        loads[target] += length
        assignments.append({"string": index, "modules": length, "mppt": target + 1})
    return assignments


def calculate_complete_project(module: dict, inverter: dict, inputs: dict) -> dict:
    module_count = int(inputs["module_count"])
    preferred = int(inputs["modules_per_string"])
    minimum_temperature = _number(inputs.get("minimum_temperature_c"), 12)
    maximum_cell_temperature = _number(inputs.get("maximum_cell_temperature_c"), 70)
    voltage_drop_limit = _number(inputs.get("voltage_drop_limit_pct"), 1.5)
    correction_factor = _number(inputs.get("correction_factor"), 0.8)

    string_check = size_strings(
        module_count=module_count,
        module_voc_v=_number(module["voc_v"]),
        module_vmp_v=_number(module["vmp_v"]),
        module_isc_a=_number(module["isc_a"]),
        voc_temp_coefficient_pct=_number(module["temp_coeff_voc_pct"]),
        vmp_temp_coefficient_pct=_number(module.get("temp_coeff_pmax_pct"), -0.35),
        minimum_temperature_c=minimum_temperature,
        maximum_cell_temperature_c=maximum_cell_temperature,
        inverter_max_dc_v=_number(inverter["max_dc_voltage_v"]),
        inverter_mppt_min_v=_number(inverter["mppt_min_v"]),
        inverter_mppt_max_v=_number(inverter["mppt_max_v"]),
        inverter_mppt_count=int(inverter["mppt_count"]),
        inverter_max_current_per_mppt_a=_number(inverter["max_input_current_mppt_a"]),
        selected_modules_per_string=preferred,
    )
    string_lengths, layout_warnings = plan_string_lengths(
        module_count,
        preferred,
        string_check.min_modules_series,
        string_check.max_modules_series,
    )
    assignments = assign_strings_to_mppts(string_lengths, int(inverter["mppt_count"]))
    parallel_by_mppt = {
        mppt: sum(1 for item in assignments if item["mppt"] == mppt)
        for mppt in range(1, int(inverter["mppt_count"]) + 1)
    }
    max_parallel = max(parallel_by_mppt.values(), default=1)

    max_string_modules = max(string_lengths)
    min_string_modules = min(string_lengths)
    cold_voc = string_check.voc_cold_v * max_string_modules
    hot_vmp = string_check.vmp_hot_v * min_string_modules
    operating_vmp = _number(module["vmp_v"]) * max_string_modules

    dc_cable = size_cable(
        _number(module["isc_a"]),
        max(operating_vmp, 1),
        _number(inputs.get("dc_cable_length_m"), 20),
        "CC",
        voltage_drop_limit,
        1.25,
        correction_factor,
        2,
    )
    ac_phases = str(inverter.get("phases") or "Monofásico")
    ac_voltage = _number(inverter.get("ac_voltage_v"), 230)
    ac_current = circuit_current(
        _number(inverter["nominal_power_kw"]),
        ac_voltage,
        "Trifásico" if ac_phases == "Trifásico" else "Monofásico",
        1.0,
        max(_number(inverter.get("efficiency_pct"), 98) / 100, 0.01),
    )
    ac_cable = size_cable(
        ac_current,
        ac_voltage,
        _number(inputs.get("ac_cable_length_m"), 15),
        "Trifásico" if ac_phases == "Trifásico" else "Monofásico",
        voltage_drop_limit,
        1.25,
        correction_factor,
        3 if ac_phases == "Trifásico" else 2,
    )

    fuse_minimum = 1.25 * _number(module["isc_a"])
    string_fuse = _next_standard(fuse_minimum, DC_PROTECTION_A)
    dc_switch = _next_standard(1.25 * _number(module["isc_a"]) * max_parallel, DC_PROTECTION_A)
    spd_dc = _next_standard(1.2 * cold_voc, DC_SPD_V)
    installed_kwp = module_count * _number(module["power_wp"]) / 1000
    dc_ac_ratio = installed_kwp / max(_number(inverter["nominal_power_kw"]), 0.01)

    warnings = list(string_check.warnings) + list(layout_warnings)
    if len(string_lengths) > int(inverter["mppt_count"]) * int(inverter.get("strings_per_mppt") or 1):
        warnings.append("A quantidade de strings supera o total de entradas informado do inversor.")
    if max_parallel * _number(module["isc_a"]) * 1.25 > _number(inverter["max_input_current_mppt_a"]):
        warnings.append("A corrente de projeto das strings paralelas supera a corrente máxima do MPPT.")
    if max_parallel * _number(module["isc_a"]) > _number(inverter["max_short_circuit_current_mppt_a"]):
        warnings.append("A corrente de curto-circuito agregada supera o limite informado do MPPT.")
    if string_fuse and string_fuse > _number(module.get("max_series_fuse_a"), string_fuse):
        warnings.append("O fusível calculado supera o máximo em série do módulo; revise o arranjo e a proteção reversa.")
    if spd_dc is None or spd_dc > _number(inverter["max_dc_voltage_v"]):
        warnings.append("Não há DPS CC padronizado compatível com a margem adotada e a tensão máxima do inversor.")
    if not 0.9 <= dc_ac_ratio <= 1.5:
        warnings.append("A relação CC/CA está fora da faixa usual de triagem (0,90 a 1,50).")
    warnings.extend(dc_cable.warnings)
    warnings.extend(ac_cable.warnings)

    return {
        "installed_kwp": installed_kwp,
        "dc_ac_ratio": dc_ac_ratio,
        "string_count": len(string_lengths),
        "string_lengths": string_lengths,
        "assignments": assignments,
        "parallel_strings_per_mppt": parallel_by_mppt,
        "minimum_modules_series": string_check.min_modules_series,
        "maximum_modules_series": string_check.max_modules_series,
        "cold_voc_v": cold_voc,
        "hot_vmp_v": hot_vmp,
        "dc_current_per_string_a": _number(module["isc_a"]) * 1.25,
        "dc_cable": asdict(dc_cable),
        "string_fuse_a": string_fuse,
        "string_fuse_required": max_parallel >= 2,
        "dc_switch_a": dc_switch,
        "dc_spd_type": "Tipo 1+2" if inputs.get("has_external_spda") else "Tipo 2",
        "dc_spd_ucpv_v": spd_dc,
        "ac_current_a": ac_current,
        "ac_cable": asdict(ac_cable),
        "ac_breaker_a": ac_cable.breaker_a,
        "ac_spd_type": "Tipo 1+2" if inputs.get("has_external_spda") else "Tipo 2",
        "ac_spd_uc_v": 460 if ac_phases == "Trifásico" else 275,
        "valid": not warnings,
        "warnings": warnings,
    }


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def generate_roof_croqui(
    project: dict,
    module: dict,
    inverter: dict,
    result: dict,
    roof_image: bytes | None = None,
) -> bytes:
    width, height = 1600, 1000
    if roof_image:
        with Image.open(BytesIO(roof_image)) as source:
            canvas = ImageOps.fit(source.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS).convert("RGBA")
        shade = Image.new("RGBA", canvas.size, (250, 252, 250, 72))
        canvas = Image.alpha_composite(canvas, shade)
    else:
        canvas = Image.new("RGBA", (width, height), "#F4F7F4")

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    title_font = _font(35, True)
    heading_font = _font(24, True)
    body_font = _font(19)
    small_font = _font(15)

    draw.rounded_rectangle((24, 22, 1576, 92), radius=18, fill=(255, 255, 255, 238), outline="#0B6E4F", width=3)
    draw.text((50, 38), f"SolarOS | Croqui fotovoltaico - {project.get('name', 'Projeto')}", font=title_font, fill="#17352B")

    roof_box = (45, 125, 1125, 800)
    draw.rounded_rectangle(roof_box, radius=24, fill=(236, 241, 237, 120), outline="#455A50", width=4)
    draw.text((68, 145), f"Vista superior | Azimute {project.get('roof_azimuth_deg', 0):.0f} graus | Inclinacao {project.get('roof_tilt_deg', 0):.0f} graus", font=body_font, fill="#17352B")

    rows = max(1, int(project.get("layout_rows") or 1))
    columns = max(1, int(project.get("layout_columns") or 1))
    module_count = int(project.get("module_count") or 1)
    gap = 10
    area_left, area_top, area_right, area_bottom = 75, 205, 1095, 765
    cell_w = (area_right - area_left - gap * (columns - 1)) / columns
    cell_h = (area_bottom - area_top - gap * (rows - 1)) / rows
    assignments_by_module: list[int] = []
    for assignment in result["assignments"]:
        assignments_by_module.extend([assignment["string"]] * assignment["modules"])

    centers_by_string: dict[int, list[tuple[float, float]]] = {}
    for index in range(module_count):
        row, column = divmod(index, columns)
        if row >= rows:
            break
        string_number = assignments_by_module[index] if index < len(assignments_by_module) else 1
        color = STRING_COLORS[(string_number - 1) % len(STRING_COLORS)]
        x1 = area_left + column * (cell_w + gap)
        y1 = area_top + row * (cell_h + gap)
        x2, y2 = x1 + cell_w, y1 + cell_h
        draw.rounded_rectangle((x1, y1, x2, y2), radius=7, fill=color + "D9", outline="#FFFFFF", width=2)
        draw.line((x1 + cell_w / 2, y1 + 4, x1 + cell_w / 2, y2 - 4), fill=(255, 255, 255, 100), width=1)
        draw.text((x1 + 7, y1 + 5), f"M{index + 1}", font=small_font, fill="white")
        draw.text((x1 + 7, y2 - 23), f"S{string_number}", font=small_font, fill="white")
        centers_by_string.setdefault(string_number, []).append(((x1 + x2) / 2, (y1 + y2) / 2))

    for string_number, centers in centers_by_string.items():
        if len(centers) > 1:
            draw.line(centers, fill=STRING_COLORS[(string_number - 1) % len(STRING_COLORS)], width=5)

    equipment_x = 1170
    draw.rounded_rectangle((equipment_x, 185, 1545, 355), radius=18, fill=(255, 255, 255, 235), outline="#0B6E4F", width=4)
    draw.text((equipment_x + 22, 205), "INVERSOR", font=heading_font, fill="#0B6E4F")
    draw.text((equipment_x + 22, 247), f"{inverter.get('manufacturer') or ''} {inverter['model']}", font=body_font, fill="#17352B")
    draw.text((equipment_x + 22, 282), f"{inverter['nominal_power_kw']:.1f} kW | {inverter['mppt_count']} MPPT", font=body_font, fill="#17352B")
    draw.text((equipment_x + 22, 317), f"Entrada: {result['string_count']} strings", font=body_font, fill="#17352B")

    draw.rounded_rectangle((equipment_x, 420, 1545, 565), radius=18, fill=(255, 255, 255, 235), outline="#E67E22", width=4)
    draw.text((equipment_x + 22, 440), "PROTECAO CA", font=heading_font, fill="#A94C00")
    draw.text((equipment_x + 22, 482), f"Cabo {result['ac_cable']['section_mm2']:.1f} mm2 | DJ {result['ac_breaker_a'] or '-'} A", font=body_font, fill="#17352B")
    draw.text((equipment_x + 22, 520), f"DPS {result['ac_spd_type']} | Uc {result['ac_spd_uc_v']} V", font=body_font, fill="#17352B")

    draw.rounded_rectangle((equipment_x, 635, 1545, 750), radius=18, fill=(255, 255, 255, 235), outline="#455A50", width=4)
    draw.text((equipment_x + 22, 655), "MEDIDOR / REDE", font=heading_font, fill="#17352B")
    draw.text((equipment_x + 22, 702), "Ponto de conexao Energisa PB", font=body_font, fill="#17352B")

    draw.line((1125, 315, equipment_x, 270), fill="#0B6E4F", width=7)
    draw.text((1090, 260), f"CC {result['dc_cable']['section_mm2']:.1f} mm2", font=small_font, fill="#0B6E4F")
    draw.line((equipment_x + 187, 355, equipment_x + 187, 420), fill="#E67E22", width=7)
    draw.line((equipment_x + 187, 565, equipment_x + 187, 635), fill="#455A50", width=7)

    draw.rounded_rectangle((35, 835, 1565, 970), radius=18, fill=(255, 255, 255, 242), outline="#B5C2BA", width=2)
    module_label = f"Modulo: {module.get('manufacturer') or ''} {module['model']} | {module['power_wp']:.0f} Wp | Total {result['installed_kwp']:.3f} kWp"
    strings_label = "Strings: " + " | ".join(f"S{i + 1}: {count} mod." for i, count in enumerate(result["string_lengths"]))
    protection_label = f"CC: cabo {result['dc_cable']['section_mm2']:.1f} mm2, fusivel {result['string_fuse_a'] or '-'} A, DPS {result['dc_spd_type']} {result['dc_spd_ucpv_v'] or '-'} V"
    draw.text((58, 855), module_label, font=body_font, fill="#17352B")
    draw.text((58, 892), strings_label, font=body_font, fill="#17352B")
    draw.text((58, 929), protection_label, font=body_font, fill="#17352B")

    if module_count > rows * columns:
        draw.text((760, 775), f"ATENCAO: grade comporta {rows * columns} de {module_count} modulos", font=body_font, fill="#B3261E")

    rendered = Image.alpha_composite(canvas, overlay).convert("RGB")
    output = BytesIO()
    rendered.save(output, format="PNG", optimize=True)
    return output.getvalue()


def extract_datasheet_hints(pdf_data: bytes, equipment_type: str) -> dict[str, float]:
    """Best-effort, offline extraction for text-based PDFs. Values must be confirmed."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return {}
    try:
        reader = PdfReader(BytesIO(pdf_data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:8])
    except Exception:
        return {}
    normalized = re.sub(r"\s+", " ", text.replace(",", "."))

    def find(patterns: list[str]) -> float | None:
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        return None

    if equipment_type == "module":
        patterns = {
            "power_wp": [r"(?:Pmax|maximum power|pot[eê]ncia m[aá]xima)[^0-9]{0,20}(\d{3,4}(?:\.\d+)?)\s*W"],
            "voc_v": [r"(?:Voc|open circuit voltage|tens[aã]o de circuito aberto)[^0-9]{0,20}(\d{1,3}(?:\.\d+)?)\s*V"],
            "vmp_v": [r"(?:Vmp|Vmpp|maximum power voltage)[^0-9]{0,20}(\d{1,3}(?:\.\d+)?)\s*V"],
            "isc_a": [r"(?:Isc|short circuit current|corrente de curto)[^0-9]{0,20}(\d{1,3}(?:\.\d+)?)\s*A"],
            "imp_a": [r"(?:Imp|Impp|maximum power current)[^0-9]{0,20}(\d{1,3}(?:\.\d+)?)\s*A"],
            "max_series_fuse_a": [r"(?:maximum series fuse|max series fuse)[^0-9]{0,20}(\d{1,3}(?:\.\d+)?)\s*A"],
        }
    else:
        patterns = {
            "nominal_power_kw": [r"(?:rated output power|nominal output power|pot[eê]ncia nominal)[^0-9]{0,25}(\d{1,6}(?:\.\d+)?)\s*kW"],
            "max_dc_voltage_v": [r"(?:max(?:imum)?\.?.? input voltage|tens[aã]o m[aá]xima de entrada)[^0-9]{0,25}(\d{2,4}(?:\.\d+)?)\s*V"],
            "max_input_current_mppt_a": [r"(?:max(?:imum)?\.?.? input current|corrente m[aá]xima de entrada)[^0-9]{0,25}(\d{1,4}(?:\.\d+)?)\s*A"],
        }
    return {key: value for key, candidates in patterns.items() if (value := find(candidates)) is not None}
