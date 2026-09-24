from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import quote

from solar_crm.calculations import money
from solar_crm.db import connect, execute, now_iso, query


SEVERITIES = ["Baixa", "Média", "Alta", "Crítica"]
STATUSES = ["Nova", "Lida", "Arquivada", "Resolvida"]
AUDIENCES = ["Todos", "Administrador", "Técnico", "Financeiro", "Comercial"]


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _deadline_severity(due: date, today: date) -> str:
    days = (due - today).days
    if days < 0:
        return "Crítica"
    if days <= 2:
        return "Alta"
    if days <= 7:
        return "Média"
    return "Baixa"


def _deadline_text(due: date, today: date) -> str:
    days = (due - today).days
    if days < 0:
        return f"vencido há {abs(days)} dia(s)"
    if days == 0:
        return "vence hoje"
    return f"vence em {days} dia(s)"


def _event(
    event_key: str,
    category: str,
    severity: str,
    title: str,
    message: str,
    *,
    audience: str = "Todos",
    row: dict | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
    due_date: str | None = None,
) -> dict:
    data = row or {}
    return {
        "event_key": event_key,
        "origin": "Automática",
        "audience": audience,
        "category": category,
        "severity": severity if severity in SEVERITIES else "Média",
        "title": title,
        "message": message,
        "client_id": data.get("client_id"),
        "plant_id": data.get("plant_id"),
        "source_type": source_type,
        "source_id": source_id,
        "due_date": due_date,
        "recipient_name": data.get("contact_name") or data.get("client_name"),
        "recipient_phone": data.get("phone") or data.get("contact_phone"),
        "recipient_email": data.get("email") or data.get("client_email"),
    }


def refresh_automatic_notifications(as_of: date | None = None, horizon_days: int = 30) -> int:
    """Synchronize actionable business deadlines into one notification inbox."""
    today = as_of or date.today()
    horizon = today + timedelta(days=max(int(horizon_days), 7))
    desired: list[dict] = []

    cash_rows = query(
        """SELECT ct.*, c.name AS client_name, c.contact_name, c.phone, c.email
           FROM cash_transactions ct
           LEFT JOIN clients c ON c.id=ct.client_id
           WHERE ct.deleted_at IS NULL AND ct.settlement_date IS NULL
             AND ct.status IN ('A receber','A pagar') AND ct.due_date<=?""",
        (horizon.isoformat(),),
    )
    for row in cash_rows:
        due = _date(row.get("due_date"))
        if not due:
            continue
        kind = "Recebimento" if row["transaction_type"] == "Receita" else "Pagamento"
        desired.append(_event(
            f"cash:{row['id']}", "Financeiro", _deadline_severity(due, today),
            f"{kind} {_deadline_text(due, today)}",
            f"{row['description']} · {money(row['amount'])}. Vencimento em {due.strftime('%d/%m/%Y')}.",
            audience="Financeiro", row=row, source_type="cash_transaction", source_id=row["id"], due_date=due.isoformat(),
        ))

    task_rows = query(
        """SELECT t.*, c.name AS client_name, c.contact_name, c.phone, c.email
           FROM tasks t LEFT JOIN clients c ON c.id=t.client_id
           WHERE t.status NOT IN ('Concluída','Cancelada') AND t.due_date<=?""",
        (horizon.isoformat(),),
    )
    for row in task_rows:
        due = _date(row.get("due_date"))
        if due:
            desired.append(_event(
                f"task:{row['id']}", "Operação", _deadline_severity(due, today),
                f"Atividade {_deadline_text(due, today)}", row["title"],
                audience="Técnico", row=row, source_type="task", source_id=row["id"], due_date=due.isoformat(),
            ))

    order_rows = query(
        """SELECT so.*, c.name AS client_name, c.contact_name, c.phone, c.email
           FROM service_orders so JOIN clients c ON c.id=so.client_id
           WHERE so.status NOT IN ('Concluída','Cancelada')
             AND so.scheduled_date IS NOT NULL AND so.scheduled_date<=?""",
        (horizon.isoformat(),),
    )
    for row in order_rows:
        due = _date(row.get("scheduled_date"))
        if due:
            desired.append(_event(
                f"service_order:{row['id']}", "Operação", _deadline_severity(due, today),
                f"O.S. {row['number']} {_deadline_text(due, today)}", row["title"],
                audience="Técnico", row=row, source_type="service_order", source_id=row["id"], due_date=due.isoformat(),
            ))

    plan_rows = query(
        """SELECT mp.*, c.name AS client_name, c.contact_name, c.phone, c.email,
                  p.name AS plant_name
           FROM maintenance_plans mp JOIN clients c ON c.id=mp.client_id
           JOIN plants p ON p.id=mp.plant_id
           WHERE mp.active=1 AND mp.next_due_date<=?""",
        (horizon.isoformat(),),
    )
    for row in plan_rows:
        due = _date(row.get("next_due_date"))
        if due:
            desired.append(_event(
                f"maintenance:{row['id']}:{due.isoformat()}", "Preventiva", _deadline_severity(due, today),
                f"Preventiva {_deadline_text(due, today)}",
                f"{row['plant_name']} · {row['name']}.", audience="Técnico", row=row,
                source_type="maintenance_plan", source_id=row["id"], due_date=due.isoformat(),
            ))

    warranty_rows = query(
        """SELECT p.id, p.id AS plant_id, p.client_id, p.name AS plant_name, p.warranty_expiry,
                  c.name AS client_name, c.contact_name, c.phone, c.email
           FROM plants p JOIN clients c ON c.id=p.client_id
           WHERE p.status!='Desativada' AND p.warranty_expiry IS NOT NULL AND p.warranty_expiry<=?""",
        ((today + timedelta(days=60)).isoformat(),),
    )
    for row in warranty_rows:
        due = _date(row.get("warranty_expiry"))
        if due:
            desired.append(_event(
                f"warranty:{row['id']}:{due.isoformat()}", "Garantia", _deadline_severity(due, today),
                f"Garantia da usina {_deadline_text(due, today)}",
                f"{row['plant_name']} · validade em {due.strftime('%d/%m/%Y')}.", audience="Técnico", row=row,
                source_type="plant", source_id=row["id"], due_date=due.isoformat(),
            ))

    fault_rows = query(
        """SELECT fc.*, f.title AS fault_title, f.severity, c.name AS client_name,
                  c.contact_name, c.phone, c.email
           FROM fault_cases fc JOIN fault_catalog f ON f.id=fc.fault_id
           JOIN clients c ON c.id=fc.client_id
           WHERE fc.status NOT IN ('Resolvida','Encerrada sem solução') AND f.severity IN ('Alta','Crítica')"""
    )
    for row in fault_rows:
        desired.append(_event(
            f"fault:{row['id']}", "Falha", row["severity"], "Falha técnica requer atenção",
            f"{row['client_name']} · {row['fault_title']}.", audience="Técnico", row=row,
            source_type="fault_case", source_id=row["id"], due_date=row.get("observed_at"),
        ))

    stock_rows = query(
        """SELECT si.id, si.name, si.unit, si.minimum_quantity,
                  COALESCE(SUM(CASE sm.movement_type
                    WHEN 'Entrada' THEN sm.quantity WHEN 'Ajuste positivo' THEN sm.quantity
                    WHEN 'Saída' THEN -sm.quantity WHEN 'Ajuste negativo' THEN -sm.quantity ELSE 0 END),0) AS balance
           FROM stock_items si LEFT JOIN stock_movements sm ON sm.item_id=si.id
           WHERE si.active=1 GROUP BY si.id HAVING COALESCE(SUM(CASE sm.movement_type
                    WHEN 'Entrada' THEN sm.quantity WHEN 'Ajuste positivo' THEN sm.quantity
                    WHEN 'Saída' THEN -sm.quantity WHEN 'Ajuste negativo' THEN -sm.quantity ELSE 0 END),0) <= si.minimum_quantity"""
    )
    for row in stock_rows:
        desired.append(_event(
            f"stock:{row['id']}", "Estoque", "Alta" if float(row["balance"]) <= 0 else "Média",
            "Estoque abaixo do mínimo", f"{row['name']}: {float(row['balance']):g} {row['unit']} disponível(is).",
            audience="Técnico", source_type="stock_item", source_id=row["id"],
        ))

    month = today.replace(day=1).isoformat()
    reading_due = today.replace(day=5).isoformat()
    reading_rows = query(
        """SELECT p.id, p.id AS plant_id, p.client_id, p.name AS plant_name,
                  c.name AS client_name, c.contact_name, c.phone, c.email
           FROM plants p JOIN clients c ON c.id=p.client_id
           WHERE p.status!='Desativada' AND NOT EXISTS (
               SELECT 1 FROM readings r WHERE r.plant_id=p.id AND r.reference_month=?
           )""",
        (month,),
    )
    for row in reading_rows:
        desired.append(_event(
            f"reading:{row['id']}:{month}", "Leitura", "Média",
            "Leitura mensal pendente", f"Lance a leitura ou fatura de {row['plant_name']} para fechar o relatório do mês.",
            audience="Financeiro", row=row, source_type="plant", source_id=row["id"], due_date=reading_due,
        ))

    now = now_iso()
    conn = connect()
    try:
        for item in desired:
            conn.execute(
                """INSERT INTO notification_events
                   (event_key, origin, audience, category, severity, title, message,
                    client_id, plant_id, source_type, source_id, due_date,
                    recipient_name, recipient_phone, recipient_email, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Nova', ?)
                   ON CONFLICT(event_key) DO UPDATE SET
                     audience=excluded.audience, category=excluded.category, severity=excluded.severity,
                     title=excluded.title, message=excluded.message, client_id=excluded.client_id,
                     plant_id=excluded.plant_id, source_type=excluded.source_type,
                     source_id=excluded.source_id, due_date=excluded.due_date,
                     recipient_name=excluded.recipient_name, recipient_phone=excluded.recipient_phone,
                     recipient_email=excluded.recipient_email,
                     status=CASE WHEN notification_events.status='Resolvida' THEN 'Nova' ELSE notification_events.status END,
                     read_at=CASE WHEN notification_events.status='Resolvida' THEN NULL ELSE notification_events.read_at END,
                     updated_at=excluded.updated_at""",
                (
                    item["event_key"], item["origin"], item["audience"], item["category"], item["severity"],
                    item["title"], item["message"], item["client_id"], item["plant_id"], item["source_type"],
                    item["source_id"], item["due_date"], item["recipient_name"], item["recipient_phone"],
                    item["recipient_email"], now,
                ),
            )
        keys = [item["event_key"] for item in desired]
        if keys:
            placeholders = ",".join("?" for _ in keys)
            conn.execute(
                f"""UPDATE notification_events SET status='Resolvida', updated_at=?
                    WHERE origin='Automática' AND status IN ('Nova','Lida')
                      AND event_key NOT IN ({placeholders})""",
                (now, *keys),
            )
        else:
            conn.execute(
                "UPDATE notification_events SET status='Resolvida', updated_at=? WHERE origin='Automática' AND status IN ('Nova','Lida')",
                (now,),
            )
        conn.commit()
    finally:
        conn.close()
    return len(desired)


def create_manual_notification(values: dict) -> int:
    title = str(values.get("title") or "").strip()
    message = str(values.get("message") or "").strip()
    if not title or not message:
        raise ValueError("Informe o título e a mensagem da notificação.")
    severity = values.get("severity") or "Média"
    audience = values.get("audience") or "Todos"
    if severity not in SEVERITIES or audience not in AUDIENCES:
        raise ValueError("Prioridade ou público inválido.")
    return execute(
        """INSERT INTO notification_events
           (event_key, origin, audience, category, severity, title, message, client_id,
            due_date, recipient_name, recipient_phone, recipient_email, status, updated_at)
           VALUES (?, 'Manual', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Nova', ?)""",
        (
            f"manual:{secrets.token_urlsafe(16)}", audience, values.get("category") or "Geral",
            severity, title, message, values.get("client_id"), values.get("due_date"),
            values.get("recipient_name"), values.get("recipient_phone"), values.get("recipient_email"), now_iso(),
        ),
    )


def notifications_for_role(role: str, include_archived: bool = False) -> list[dict]:
    rows = query(
        """SELECT ne.*, c.name AS client_name, p.name AS plant_name
           FROM notification_events ne
           LEFT JOIN clients c ON c.id=ne.client_id
           LEFT JOIN plants p ON p.id=ne.plant_id
           ORDER BY CASE ne.status WHEN 'Nova' THEN 1 WHEN 'Lida' THEN 2 WHEN 'Arquivada' THEN 3 ELSE 4 END,
                    CASE ne.severity WHEN 'Crítica' THEN 1 WHEN 'Alta' THEN 2 WHEN 'Média' THEN 3 ELSE 4 END,
                    ne.due_date, ne.created_at DESC"""
    )
    allowed = rows if role == "Administrador" else [row for row in rows if row["audience"] in {"Todos", role}]
    return allowed if include_archived else [row for row in allowed if row["status"] not in {"Arquivada", "Resolvida"}]


def notification_counts(role: str) -> dict[str, int]:
    rows = notifications_for_role(role)
    return {
        "new": sum(row["status"] == "Nova" for row in rows),
        "critical": sum(row["severity"] == "Crítica" for row in rows),
        "total": len(rows),
    }


def set_notification_status(notification_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError("Status de notificação inválido.")
    execute(
        """UPDATE notification_events SET status=?, read_at=CASE WHEN ?='Lida' THEN ? ELSE read_at END,
           archived_at=CASE WHEN ?='Arquivada' THEN ? ELSE archived_at END, updated_at=? WHERE id=?""",
        (status, status, now_iso(), status, now_iso(), now_iso(), notification_id),
    )


def whatsapp_url(notification: dict) -> str | None:
    phone = re.sub(r"\D", "", str(notification.get("recipient_phone") or ""))
    if not phone:
        return None
    if len(phone) in {10, 11}:
        phone = f"55{phone}"
    recipient = notification.get("recipient_name") or notification.get("client_name") or "cliente"
    message = f"Olá, {recipient}. {notification['title']}: {notification['message']}"
    return f"https://wa.me/{phone}?text={quote(message)}"
