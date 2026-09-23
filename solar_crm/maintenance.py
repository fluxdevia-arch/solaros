from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from solar_crm.db import execute, now_iso, query, query_one
from solar_crm.workflow import create_service_order


MOVEMENT_TYPES = ["Entrada", "Saída", "Ajuste positivo", "Ajuste negativo"]


def _add_months(value: date, months: int) -> date:
    target = value.month - 1 + months
    year = value.year + target // 12
    month = target % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def create_maintenance_plan(values: dict) -> int:
    name = str(values.get("name") or "").strip()
    description = str(values.get("work_description") or "").strip()
    if not values.get("client_id") or not values.get("plant_id") or not name or not description:
        raise ValueError("Informe cliente, usina, nome e escopo da manutenção preventiva.")
    frequency = int(values.get("frequency_months") or 0)
    if frequency < 1 or frequency > 60:
        raise ValueError("A periodicidade deve ficar entre 1 e 60 meses.")
    return execute(
        """INSERT INTO maintenance_plans
           (client_id, plant_id, contract_id, checklist_template_id, name,
            frequency_months, next_due_date, lead_days, priority, assignee,
            work_description, safety_instructions, active, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
        (
            values["client_id"], values["plant_id"], values.get("contract_id"),
            values.get("checklist_template_id"), name, frequency,
            values.get("next_due_date") or date.today().isoformat(),
            max(int(values.get("lead_days") or 0), 0), values.get("priority") or "Média",
            values.get("assignee"), description, values.get("safety_instructions"), now_iso(),
        ),
    )


def maintenance_plans(active_only: bool = False) -> list[dict]:
    where = "WHERE mp.active=1" if active_only else ""
    return query(
        f"""SELECT mp.*, c.name AS client_name, p.name AS plant_name, p.unit_code,
                   p.address AS plant_address, c.contact_name, c.phone AS contact_phone,
                   ct.plan AS contract_name, ict.name AS checklist_name,
                   (SELECT COUNT(*) FROM maintenance_occurrences mo WHERE mo.plan_id=mp.id) AS generated_count
            FROM maintenance_plans mp
            JOIN clients c ON c.id=mp.client_id
            JOIN plants p ON p.id=mp.plant_id
            LEFT JOIN contracts ct ON ct.id=mp.contract_id
            LEFT JOIN inspection_checklist_templates ict ON ict.id=mp.checklist_template_id
            {where}
            ORDER BY mp.active DESC, mp.next_due_date, c.name, p.name"""
    )


def generate_due_maintenance_orders(as_of: date | None = None, horizon_days: int = 45) -> list[int]:
    today = as_of or date.today()
    created: list[int] = []
    for plan in maintenance_plans(active_only=True):
        horizon = today + timedelta(days=max(int(horizon_days), int(plan.get("lead_days") or 0), 0))
        due = date.fromisoformat(str(plan["next_due_date"])[:10])
        guard = 0
        while due <= horizon and guard < 24:
            existing = query_one(
                "SELECT service_order_id FROM maintenance_occurrences WHERE plan_id=? AND scheduled_date=?",
                (plan["id"], due.isoformat()),
            )
            if not existing:
                order_id = create_service_order({
                    "client_id": plan["client_id"], "plant_id": plan["plant_id"],
                    "title": plan["name"], "service_type": "Manutenção preventiva",
                    "priority": plan["priority"], "status": "Agendada",
                    "requested_at": datetime.now().isoformat(timespec="seconds"),
                    "scheduled_date": due.isoformat(), "assignee": plan.get("assignee"),
                    "address": plan.get("plant_address") or "Endereço da usina não informado",
                    "contact_name": plan.get("contact_name"), "contact_phone": plan.get("contact_phone"),
                    "work_description": plan["work_description"],
                    "safety_instructions": plan.get("safety_instructions"),
                    "materials": "Separar materiais após conferência do estoque e da última vistoria.",
                })
                execute(
                    "INSERT INTO maintenance_occurrences (plan_id, scheduled_date, service_order_id) VALUES (?, ?, ?)",
                    (plan["id"], due.isoformat(), order_id),
                )
                created.append(order_id)
            due = _add_months(due, int(plan["frequency_months"]))
            guard += 1
        execute("UPDATE maintenance_plans SET next_due_date=?, updated_at=? WHERE id=?", (due.isoformat(), now_iso(), plan["id"]))
    return created


def update_maintenance_plan_status(plan_id: int, active: bool) -> None:
    execute("UPDATE maintenance_plans SET active=?, updated_at=? WHERE id=?", (int(active), now_iso(), plan_id))


def update_maintenance_plan(plan_id: int, values: dict) -> None:
    frequency = int(values.get("frequency_months") or 0)
    if frequency < 1 or frequency > 60:
        raise ValueError("A periodicidade deve ficar entre 1 e 60 meses.")
    execute(
        """UPDATE maintenance_plans SET frequency_months=?, next_due_date=?, lead_days=?,
           priority=?, assignee=?, work_description=?, safety_instructions=?, updated_at=?
           WHERE id=?""",
        (
            frequency, values["next_due_date"], max(int(values.get("lead_days") or 0), 0),
            values.get("priority") or "Média", values.get("assignee"),
            values.get("work_description"), values.get("safety_instructions"), now_iso(), plan_id,
        ),
    )


def create_stock_item(values: dict) -> int:
    name = str(values.get("name") or "").strip()
    if not name:
        raise ValueError("Informe o nome do item de estoque.")
    item_id = execute(
        """INSERT INTO stock_items
           (sku, name, category, unit, minimum_quantity, location, active, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
        (
            str(values.get("sku") or "").strip() or None, name,
            values.get("category") or "Outros", values.get("unit") or "un",
            max(float(values.get("minimum_quantity") or 0), 0), values.get("location"), now_iso(),
        ),
    )
    initial = float(values.get("initial_quantity") or 0)
    if initial > 0:
        record_stock_movement(item_id, "Entrada", initial, float(values.get("unit_cost") or 0), notes="Saldo inicial")
    return item_id


def update_stock_item(item_id: int, values: dict) -> None:
    name = str(values.get("name") or "").strip()
    if not name:
        raise ValueError("Informe o nome do item de estoque.")
    execute(
        """UPDATE stock_items SET sku=?, name=?, category=?, unit=?, minimum_quantity=?,
           location=?, active=?, updated_at=? WHERE id=?""",
        (
            str(values.get("sku") or "").strip() or None, name,
            values.get("category") or "Outros", values.get("unit") or "un",
            max(float(values.get("minimum_quantity") or 0), 0), values.get("location"),
            int(bool(values.get("active", True))), now_iso(), item_id,
        ),
    )


def stock_items(active_only: bool = True) -> list[dict]:
    where = "WHERE si.active=1" if active_only else ""
    return query(
        f"""SELECT si.*,
                   COALESCE(SUM(CASE sm.movement_type
                       WHEN 'Entrada' THEN sm.quantity WHEN 'Ajuste positivo' THEN sm.quantity
                       WHEN 'Saída' THEN -sm.quantity WHEN 'Ajuste negativo' THEN -sm.quantity ELSE 0 END), 0) AS balance,
                   COALESCE(SUM(CASE WHEN sm.movement_type IN ('Entrada','Ajuste positivo')
                       THEN sm.quantity * sm.unit_cost ELSE 0 END), 0) AS entry_value
            FROM stock_items si LEFT JOIN stock_movements sm ON sm.item_id=si.id
            {where} GROUP BY si.id ORDER BY si.name"""
    )


def record_stock_movement(
    item_id: int,
    movement_type: str,
    quantity: float,
    unit_cost: float = 0,
    service_order_id: int | None = None,
    moved_at: str | None = None,
    notes: str = "",
) -> int:
    if movement_type not in MOVEMENT_TYPES:
        raise ValueError("Tipo de movimentação inválido.")
    quantity = float(quantity)
    if quantity <= 0:
        raise ValueError("A quantidade deve ser maior que zero.")
    item = query_one(
        """SELECT si.*,
                  COALESCE(SUM(CASE sm.movement_type
                    WHEN 'Entrada' THEN sm.quantity WHEN 'Ajuste positivo' THEN sm.quantity
                    WHEN 'Saída' THEN -sm.quantity WHEN 'Ajuste negativo' THEN -sm.quantity ELSE 0 END),0) AS balance
           FROM stock_items si LEFT JOIN stock_movements sm ON sm.item_id=si.id
           WHERE si.id=? GROUP BY si.id""",
        (item_id,),
    )
    if not item:
        raise ValueError("Item de estoque não encontrado.")
    if movement_type in {"Saída", "Ajuste negativo"} and quantity > float(item["balance"]):
        raise ValueError(f"Saldo insuficiente. Disponível: {float(item['balance']):g} {item['unit']}.")
    return execute(
        """INSERT INTO stock_movements
           (item_id, service_order_id, movement_type, quantity, unit_cost, moved_at, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (item_id, service_order_id, movement_type, quantity, max(float(unit_cost or 0), 0), moved_at or now_iso(), notes.strip()),
    )


def stock_movements(limit: int = 250) -> list[dict]:
    return query(
        """SELECT sm.*, si.sku, si.name AS item_name, si.unit, so.number AS service_order_number
           FROM stock_movements sm JOIN stock_items si ON si.id=sm.item_id
           LEFT JOIN service_orders so ON so.id=sm.service_order_id
           ORDER BY sm.moved_at DESC, sm.id DESC LIMIT ?""",
        (max(int(limit), 1),),
    )


def service_order_stock_movements(service_order_id: int) -> list[dict]:
    return query(
        """SELECT sm.*, si.name AS item_name, si.unit
           FROM stock_movements sm JOIN stock_items si ON si.id=sm.item_id
           WHERE sm.service_order_id=? ORDER BY sm.moved_at, sm.id""",
        (service_order_id,),
    )
