from __future__ import annotations

import secrets
from datetime import datetime
from urllib.parse import quote

from solar_crm.db import execute, now_iso, query_one


OPPORTUNITY_STAGES = [
    "Lead recebido",
    "Diagnóstico",
    "Proposta enviada",
    "Negociação",
    "Fechado ganho",
    "Fechado perdido",
]

SERVICE_ORDER_STATUSES = [
    "Aberta",
    "Agendada",
    "Em deslocamento",
    "Em execução",
    "Concluída",
    "Impedida",
    "Cancelada",
]

CONTRACT_STATUSES = ["Rascunho", "Emitido", "Enviado", "Assinado", "Cancelado"]


def create_opportunity(values: dict) -> int:
    lead_name = str(values.get("lead_name") or "").strip()
    service_type = str(values.get("service_type") or "").strip()
    if not lead_name:
        raise ValueError("Informe o nome do cliente ou da oportunidade.")
    if not service_type:
        raise ValueError("Informe o serviço negociado.")
    stage = values.get("stage") or OPPORTUNITY_STAGES[0]
    if stage not in OPPORTUNITY_STAGES:
        raise ValueError("Etapa comercial inválida.")
    return execute(
        """INSERT INTO opportunities
           (client_id, lead_name, company, contact_name, phone, email, service_type,
            source, stage, estimated_value, probability_pct, expected_close_date,
            next_action, next_action_date, owner, notes, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            values.get("client_id"), lead_name, values.get("company"), values.get("contact_name"),
            values.get("phone"), values.get("email"), service_type, values.get("source"), stage,
            max(float(values.get("estimated_value") or 0), 0),
            min(max(float(values.get("probability_pct") or 0), 0), 100),
            values.get("expected_close_date"), values.get("next_action"), values.get("next_action_date"),
            values.get("owner"), values.get("notes"), now_iso(),
        ),
    )


def move_opportunity(opportunity_id: int, direction: int) -> str:
    opportunity = query_one("SELECT stage FROM opportunities WHERE id=?", (opportunity_id,))
    if not opportunity:
        raise ValueError("Oportunidade não encontrada.")
    current = OPPORTUNITY_STAGES.index(opportunity["stage"])
    target = min(max(current + direction, 0), len(OPPORTUNITY_STAGES) - 1)
    stage = OPPORTUNITY_STAGES[target]
    execute("UPDATE opportunities SET stage=?, updated_at=? WHERE id=?", (stage, now_iso(), opportunity_id))
    return stage


def set_opportunity_stage(opportunity_id: int, stage: str, lost_reason: str = "") -> None:
    if stage not in OPPORTUNITY_STAGES:
        raise ValueError("Etapa comercial inválida.")
    execute(
        "UPDATE opportunities SET stage=?, lost_reason=?, updated_at=? WHERE id=?",
        (stage, lost_reason.strip() if stage == "Fechado perdido" else None, now_iso(), opportunity_id),
    )


def create_service_order(values: dict) -> int:
    title = str(values.get("title") or "").strip()
    address = str(values.get("address") or "").strip()
    description = str(values.get("work_description") or "").strip()
    if not values.get("client_id") or not title or not address or not description:
        raise ValueError("Informe cliente, título, endereço e serviço a executar.")
    order_id = execute(
        """INSERT INTO service_orders
           (public_token, client_id, plant_id, title, service_type, priority, status,
            requested_at, scheduled_date, assignee, address, contact_name, contact_phone,
            work_description, safety_instructions, materials, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            secrets.token_urlsafe(24), values["client_id"], values.get("plant_id"), title,
            values.get("service_type") or "Outro", values.get("priority") or "Média",
            values.get("status") or "Aberta", values.get("requested_at") or now_iso(),
            values.get("scheduled_date"), values.get("assignee"), address,
            values.get("contact_name"), values.get("contact_phone"), description,
            values.get("safety_instructions"), values.get("materials"), now_iso(),
        ),
    )
    number = f"OS-{datetime.now():%Y}-{order_id:05d}"
    execute("UPDATE service_orders SET number=? WHERE id=?", (number, order_id))
    return order_id


def update_service_order(order_id: int, status: str, completion_notes: str = "", assignee: str = "") -> None:
    if status not in SERVICE_ORDER_STATUSES:
        raise ValueError("Status de ordem de serviço inválido.")
    completed_at = now_iso() if status == "Concluída" else None
    execute(
        """UPDATE service_orders SET status=?, completion_notes=?,
           assignee=CASE WHEN ?!='' THEN ? ELSE assignee END,
           completed_at=?, updated_at=? WHERE id=?""",
        (status, completion_notes.strip(), assignee.strip(), assignee.strip(), completed_at, now_iso(), order_id),
    )


def service_order_by_token(token: str) -> dict | None:
    if not token or len(token) < 20:
        return None
    return query_one(
        """SELECT so.*, c.name AS client_name, c.email AS client_email,
                  p.name AS plant_name, p.unit_code, p.inverter, p.modules
           FROM service_orders so
           JOIN clients c ON c.id=so.client_id
           LEFT JOIN plants p ON p.id=so.plant_id
           WHERE so.public_token=?""",
        (token,),
    )


def service_order_share_url(order: dict, base_url: str) -> str:
    base = (base_url or "http://localhost:8501").strip().rstrip("/")
    return f"{base}/service-orders?os={quote(order['public_token'])}"


def regenerate_service_order_token(order_id: int) -> str:
    token = secrets.token_urlsafe(24)
    execute("UPDATE service_orders SET public_token=?, updated_at=? WHERE id=?", (token, now_iso(), order_id))
    return token


def create_service_contract(values: dict) -> int:
    title = str(values.get("title") or "").strip()
    scope = str(values.get("scope") or "").strip()
    if not values.get("client_id") or not title or not scope:
        raise ValueError("Informe cliente, título e escopo do contrato.")
    contract_id = execute(
        """INSERT INTO service_contracts
           (client_id, contract_type, title, start_date, end_date, duration_months,
            amount, billing_cycle, payment_terms, scope, contractor_obligations,
            client_obligations, termination_terms, additional_terms, venue, status, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            values["client_id"], values.get("contract_type") or "Prestação de serviços",
            title, values["start_date"], values.get("end_date"),
            max(int(values.get("duration_months") or 1), 1), max(float(values.get("amount") or 0), 0),
            values.get("billing_cycle") or "Mensal", values.get("payment_terms"), scope,
            values.get("contractor_obligations"), values.get("client_obligations"),
            values.get("termination_terms"), values.get("additional_terms"), values.get("venue"),
            values.get("status") or "Rascunho", now_iso(),
        ),
    )
    number = f"CTR-{datetime.now():%Y}-{contract_id:05d}"
    execute("UPDATE service_contracts SET number=? WHERE id=?", (number, contract_id))
    return contract_id


def update_contract_status(contract_id: int, status: str) -> None:
    if status not in CONTRACT_STATUSES:
        raise ValueError("Status de contrato inválido.")
    execute("UPDATE service_contracts SET status=?, updated_at=? WHERE id=?", (status, now_iso(), contract_id))
