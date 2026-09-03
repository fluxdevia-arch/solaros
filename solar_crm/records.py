from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from solar_crm.db import execute, now_iso


PROPOSAL_STATUSES = ["Rascunho", "Emitida", "Enviada", "Aprovada", "Recusada", "Expirada"]
SIZING_PROJECT_STATUSES = ["Rascunho", "Em revisão", "Concluído", "Cancelado"]


def create_pv_module(values: dict, datasheet: bytes | None = None) -> int:
    if datasheet and len(datasheet) > 8 * 1024 * 1024:
        raise ValueError("O datasheet deve ter no máximo 8 MB.")
    model = str(values.get("model") or "").strip()
    required = ["power_wp", "voc_v", "vmp_v", "isc_a", "imp_a"]
    if not model or any(float(values.get(key) or 0) <= 0 for key in required):
        raise ValueError("Informe modelo, potência, Voc, Vmp, Isc e Imp do módulo.")
    return execute(
        """INSERT INTO pv_modules
           (manufacturer, model, power_wp, voc_v, vmp_v, isc_a, imp_a,
            temp_coeff_voc_pct, temp_coeff_pmax_pct, max_series_fuse_a,
            width_mm, height_mm, datasheet_name, datasheet_mime, datasheet_data, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(values.get("manufacturer") or "").strip(), model,
            float(values["power_wp"]), float(values["voc_v"]), float(values["vmp_v"]),
            float(values["isc_a"]), float(values["imp_a"]),
            float(values.get("temp_coeff_voc_pct") or -0.25),
            float(values.get("temp_coeff_pmax_pct") or -0.35),
            float(values.get("max_series_fuse_a") or 25),
            float(values.get("width_mm") or 1134), float(values.get("height_mm") or 2278),
            values.get("datasheet_name"), values.get("datasheet_mime"), datasheet,
            str(values.get("notes") or "").strip(),
        ),
    )


def create_pv_inverter(values: dict, datasheet: bytes | None = None) -> int:
    if datasheet and len(datasheet) > 8 * 1024 * 1024:
        raise ValueError("O datasheet deve ter no máximo 8 MB.")
    model = str(values.get("model") or "").strip()
    required = [
        "nominal_power_kw", "max_dc_power_kw", "max_dc_voltage_v", "mppt_min_v",
        "mppt_max_v", "mppt_count", "strings_per_mppt", "max_input_current_mppt_a",
        "max_short_circuit_current_mppt_a", "ac_voltage_v", "efficiency_pct",
    ]
    if not model or any(float(values.get(key) or 0) <= 0 for key in required):
        raise ValueError("Preencha todos os limites elétricos obrigatórios do inversor.")
    if float(values["mppt_min_v"]) >= float(values["mppt_max_v"]):
        raise ValueError("A tensão mínima MPPT deve ser menor que a tensão máxima MPPT.")
    return execute(
        """INSERT INTO pv_inverters
           (manufacturer, model, nominal_power_kw, max_dc_power_kw, max_dc_voltage_v,
            mppt_min_v, mppt_max_v, mppt_count, strings_per_mppt,
            max_input_current_mppt_a, max_short_circuit_current_mppt_a,
            ac_voltage_v, phases, efficiency_pct, datasheet_name, datasheet_mime,
            datasheet_data, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(values.get("manufacturer") or "").strip(), model,
            float(values["nominal_power_kw"]), float(values["max_dc_power_kw"]),
            float(values["max_dc_voltage_v"]), float(values["mppt_min_v"]),
            float(values["mppt_max_v"]), int(values["mppt_count"]),
            int(values["strings_per_mppt"]), float(values["max_input_current_mppt_a"]),
            float(values["max_short_circuit_current_mppt_a"]), float(values["ac_voltage_v"]),
            values.get("phases") or "Monofásico", float(values["efficiency_pct"]),
            values.get("datasheet_name"), values.get("datasheet_mime"), datasheet,
            str(values.get("notes") or "").strip(),
        ),
    )


def create_sizing_project(
    values: dict,
    result: dict,
    roof_image: bytes | None = None,
) -> int:
    if roof_image and len(roof_image) > 12 * 1024 * 1024:
        raise ValueError("A imagem da cobertura deve ter no máximo 12 MB.")
    name = str(values.get("name") or "").strip()
    if not name or not values.get("module_id") or not values.get("inverter_id"):
        raise ValueError("Informe o nome do projeto, o módulo e o inversor.")
    if int(values.get("layout_rows") or 0) * int(values.get("layout_columns") or 0) < int(values.get("module_count") or 0):
        raise ValueError("A grade do croqui precisa comportar todos os módulos.")
    project_id = execute(
        """INSERT INTO sizing_projects
           (client_id, name, address, module_id, inverter_id, module_count,
            modules_per_string, layout_rows, layout_columns, module_orientation,
            roof_type, roof_azimuth_deg, roof_tilt_deg, minimum_temperature_c,
            maximum_cell_temperature_c, dc_cable_length_m, ac_cable_length_m,
            voltage_drop_limit_pct, correction_factor, has_external_spda,
            roof_image_name, roof_image_mime, roof_image_data, result_json,
            notes, status, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            values.get("client_id"), name, values.get("address"), values["module_id"],
            values["inverter_id"], int(values["module_count"]), int(values["modules_per_string"]),
            int(values["layout_rows"]), int(values["layout_columns"]),
            values.get("module_orientation") or "Retrato", values.get("roof_type"),
            float(values.get("roof_azimuth_deg") or 0), float(values.get("roof_tilt_deg") or 0),
            float(values.get("minimum_temperature_c") or 12),
            float(values.get("maximum_cell_temperature_c") or 70),
            float(values.get("dc_cable_length_m") or 20), float(values.get("ac_cable_length_m") or 15),
            float(values.get("voltage_drop_limit_pct") or 1.5),
            float(values.get("correction_factor") or 0.8),
            int(bool(values.get("has_external_spda"))), values.get("roof_image_name"),
            values.get("roof_image_mime"), roof_image,
            json.dumps(result, ensure_ascii=False), str(values.get("notes") or "").strip(),
            values.get("status") or "Rascunho", now_iso(),
        ),
    )
    execute("UPDATE sizing_projects SET number=? WHERE id=?", (f"DIM-{datetime.now():%Y}-{project_id:05d}", project_id))
    return project_id


def create_proposal(values: dict) -> int:
    title = str(values.get("title") or "").strip()
    scope = str(values.get("scope") or "").strip()
    if not values.get("client_id") or not title or not scope:
        raise ValueError("Informe cliente, título e escopo da proposta.")
    status = values.get("status") or "Rascunho"
    if status not in PROPOSAL_STATUSES:
        raise ValueError("Status de proposta inválido.")
    proposal_id = execute(
        """INSERT INTO proposals
           (client_id, opportunity_id, title, service_type, issue_date, valid_until,
            amount, payment_terms, scope, deliverables, exclusions, deadline_days,
            status, notes, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            values["client_id"], values.get("opportunity_id"), title,
            values.get("service_type") or "Consultoria técnica", values["issue_date"],
            values["valid_until"], max(float(values.get("amount") or 0), 0),
            values.get("payment_terms"), scope, values.get("deliverables"),
            values.get("exclusions"), max(int(values.get("deadline_days") or 1), 1),
            status, values.get("notes"), now_iso(),
        ),
    )
    execute("UPDATE proposals SET number=? WHERE id=?", (f"PROP-{datetime.now():%Y}-{proposal_id:05d}", proposal_id))
    return proposal_id


def update_proposal_status(proposal_id: int, status: str) -> None:
    if status not in PROPOSAL_STATUSES:
        raise ValueError("Status de proposta inválido.")
    execute("UPDATE proposals SET status=?, updated_at=? WHERE id=?", (status, now_iso(), proposal_id))
