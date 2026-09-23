from __future__ import annotations

from datetime import date
from typing import Any

from solar_crm.db import execute, now_iso, query, query_one
from solar_crm.workflow import create_service_order


FAULT_SEVERITIES = ["Baixa", "Média", "Alta", "Crítica"]
CASE_STATUSES = [
    "Identificada",
    "Em correção",
    "Aguardando reverificação",
    "Resolvida",
    "Encerrada sem solução",
]
RECHECK_RESULTS = ["Resolvida", "Persistente", "Inconclusiva"]
KNOWN_MANUFACTURERS = [
    "Multimarcas",
    "Growatt",
    "Solis",
    "GoodWe",
    "Deye / Solarman",
    "Huawei",
    "Sungrow",
    "SAJ",
    "Solplanet",
    "RENAC",
    "AUXSOL",
    "CHINT",
    "SofarSolar",
    "Fronius",
    "WEG",
    "PHB",
]


def list_faults(*, active_only: bool = True) -> list[dict[str, Any]]:
    where = "WHERE active=1" if active_only else ""
    return query(
        f"""SELECT * FROM fault_catalog {where}
            ORDER BY CASE severity WHEN 'Crítica' THEN 1 WHEN 'Alta' THEN 2
                                   WHEN 'Média' THEN 3 ELSE 4 END,
                     manufacturer, symptom_category, title"""
    )


def fault_by_id(fault_id: int) -> dict[str, Any] | None:
    return query_one("SELECT * FROM fault_catalog WHERE id=?", (int(fault_id),))


def matching_faults(
    *,
    manufacturer: str = "",
    symptom_category: str = "",
    code_or_text: str = "",
) -> list[dict[str, Any]]:
    faults = list_faults()
    manufacturer_key = manufacturer.strip().casefold()
    symptom_key = symptom_category.strip().casefold()
    search_key = code_or_text.strip().casefold()
    result: list[dict[str, Any]] = []
    for row in faults:
        row_manufacturer = str(row.get("manufacturer") or "").casefold()
        if manufacturer_key and row_manufacturer not in {manufacturer_key, "multimarcas"}:
            continue
        if symptom_key and str(row.get("symptom_category") or "").casefold() != symptom_key:
            continue
        if search_key:
            searchable = " ".join(
                str(row.get(field) or "")
                for field in (
                    "code", "title", "symptoms", "probable_causes",
                    "verification_steps", "correction_steps", "manufacturer",
                )
            ).casefold()
            if search_key not in searchable:
                continue
        result.append(row)
    return result


def create_fault_entry(values: dict[str, Any]) -> int:
    title = str(values.get("title") or "").strip()
    symptoms = str(values.get("symptoms") or "").strip()
    causes = str(values.get("probable_causes") or "").strip()
    verification = str(values.get("verification_steps") or "").strip()
    correction = str(values.get("correction_steps") or "").strip()
    if not all((title, symptoms, causes, verification, correction)):
        raise ValueError("Informe título, sintomas, causas, verificações e correção.")
    severity = str(values.get("severity") or "Média")
    if severity not in FAULT_SEVERITIES:
        raise ValueError("Severidade inválida.")
    manufacturer = str(values.get("manufacturer") or "Multimarcas").strip()
    code = str(values.get("code") or "").strip()
    if query_one(
        "SELECT id FROM fault_catalog WHERE manufacturer=? AND code=? AND title=?",
        (manufacturer, code, title),
    ):
        raise ValueError("Esta orientação já está cadastrada para o fabricante e código informados.")
    return execute(
        """INSERT INTO fault_catalog
           (manufacturer, model_scope, code, title, symptom_category, severity,
            symptoms, probable_causes, verification_steps, correction_steps,
            safety_notes, source_reference, is_system, active, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?)""",
        (
            manufacturer,
            str(values.get("model_scope") or "").strip(),
            code,
            title,
            str(values.get("symptom_category") or "Outro").strip(),
            severity,
            symptoms,
            causes,
            verification,
            correction,
            str(values.get("safety_notes") or "").strip(),
            str(values.get("source_reference") or "").strip(),
            now_iso(),
        ),
    )


def create_fault_case(values: dict[str, Any]) -> int:
    fault_id = int(values.get("fault_id") or 0)
    client_id = int(values.get("client_id") or 0)
    if not fault_id or not fault_by_id(fault_id):
        raise ValueError("Selecione uma falha válida.")
    if not client_id:
        raise ValueError("Selecione o cliente.")
    observed_at = str(values.get("observed_at") or date.today().isoformat())[:10]
    return execute(
        """INSERT INTO fault_cases
           (fault_id, client_id, plant_id, status, observed_at, symptom_notes,
            measurements_before, diagnosis_notes, updated_at)
           VALUES (?, ?, ?, 'Identificada', ?, ?, ?, ?, ?)""",
        (
            fault_id,
            client_id,
            values.get("plant_id"),
            observed_at,
            str(values.get("symptom_notes") or "").strip(),
            str(values.get("measurements_before") or "").strip(),
            str(values.get("diagnosis_notes") or "").strip(),
            now_iso(),
        ),
    )


def list_fault_cases() -> list[dict[str, Any]]:
    return query(
        """SELECT fc.*, f.manufacturer, f.code, f.title AS fault_title,
                  f.symptom_category, f.severity, f.verification_steps,
                  f.correction_steps, f.safety_notes,
                  c.name AS client_name, c.address AS client_address,
                  c.city AS client_city, c.state AS client_state,
                  c.contact_name, c.phone AS contact_phone,
                  COALESCE(p.name, 'Serviço geral') AS plant_name,
                  p.address AS plant_address, p.inverter,
                  so.number AS service_order_number, so.status AS service_order_status
           FROM fault_cases fc
           JOIN fault_catalog f ON f.id=fc.fault_id
           JOIN clients c ON c.id=fc.client_id
           LEFT JOIN plants p ON p.id=fc.plant_id
           LEFT JOIN service_orders so ON so.id=fc.service_order_id
           ORDER BY CASE fc.status WHEN 'Resolvida' THEN 2
                                   WHEN 'Encerrada sem solução' THEN 3 ELSE 1 END,
                    fc.observed_at DESC, fc.id DESC"""
    )


def fault_case_by_id(case_id: int) -> dict[str, Any] | None:
    rows = [row for row in list_fault_cases() if int(row["id"]) == int(case_id)]
    return rows[0] if rows else None


def create_corrective_order(
    case_id: int,
    *,
    scheduled_date: str | None = None,
    assignee: str = "",
) -> int:
    case = fault_case_by_id(case_id)
    if not case:
        raise ValueError("Caso técnico não encontrado.")
    if case.get("service_order_id"):
        return int(case["service_order_id"])
    address = str(case.get("plant_address") or "").strip()
    if not address:
        address = ", ".join(
            value for value in (
                str(case.get("client_address") or "").strip(),
                str(case.get("client_city") or "").strip(),
                str(case.get("client_state") or "").strip(),
            ) if value
        )
    if not address:
        raise ValueError("Cadastre o endereço do cliente ou da usina antes de gerar a O.S.")
    work_description = "\n\n".join(
        part for part in (
            f"Falha vinculada: {case.get('code') or '-'} · {case['fault_title']}",
            f"Sintoma informado: {case.get('symptom_notes') or 'Não detalhado.'}",
            f"Medições iniciais: {case.get('measurements_before') or 'Não registradas.'}",
            f"Verificações recomendadas: {case.get('verification_steps') or '-'}",
            f"Correção orientativa: {case.get('correction_steps') or '-'}",
        ) if part
    )
    order_id = create_service_order(
        {
            "client_id": case["client_id"],
            "plant_id": case.get("plant_id"),
            "title": f"Correção · {case['fault_title']}",
            "service_type": "Manutenção corretiva",
            "priority": "Crítica" if case["severity"] == "Crítica" else ("Alta" if case["severity"] == "Alta" else "Média"),
            "status": "Agendada" if scheduled_date else "Aberta",
            "scheduled_date": scheduled_date,
            "assignee": assignee,
            "address": address,
            "contact_name": case.get("contact_name"),
            "contact_phone": case.get("contact_phone"),
            "work_description": work_description,
            "safety_instructions": case.get("safety_notes"),
            "materials": "Confirmar materiais após diagnóstico em campo.",
        }
    )
    execute(
        "UPDATE fault_cases SET service_order_id=?, status='Em correção', updated_at=? WHERE id=?",
        (order_id, now_iso(), int(case_id)),
    )
    return order_id


def record_solution(case_id: int, solution_applied: str, parts_replaced: str = "") -> None:
    solution = solution_applied.strip()
    if not solution:
        raise ValueError("Descreva a solução aplicada.")
    if not fault_case_by_id(case_id):
        raise ValueError("Caso técnico não encontrado.")
    execute(
        """UPDATE fault_cases
           SET solution_applied=?, parts_replaced=?, status='Aguardando reverificação',
               solved_at=NULL, updated_at=? WHERE id=?""",
        (solution, parts_replaced.strip(), now_iso(), int(case_id)),
    )


def record_recheck(
    case_id: int,
    *,
    checked_at: str,
    technician: str,
    measurements_after: str,
    result: str,
    notes: str = "",
) -> int:
    if result not in RECHECK_RESULTS:
        raise ValueError("Resultado de reverificação inválido.")
    if not fault_case_by_id(case_id):
        raise ValueError("Caso técnico não encontrado.")
    recheck_id = execute(
        """INSERT INTO fault_rechecks
           (case_id, checked_at, technician, measurements_after, result, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            int(case_id), checked_at[:10], technician.strip(), measurements_after.strip(),
            result, notes.strip(),
        ),
    )
    if result == "Resolvida":
        status = "Resolvida"
        solved_at = checked_at[:10]
    elif result == "Persistente":
        status = "Em correção"
        solved_at = None
    else:
        status = "Aguardando reverificação"
        solved_at = None
    execute(
        "UPDATE fault_cases SET status=?, solved_at=?, updated_at=? WHERE id=?",
        (status, solved_at, now_iso(), int(case_id)),
    )
    return recheck_id


def list_rechecks(case_id: int) -> list[dict[str, Any]]:
    return query(
        "SELECT * FROM fault_rechecks WHERE case_id=? ORDER BY checked_at DESC, id DESC",
        (int(case_id),),
    )
