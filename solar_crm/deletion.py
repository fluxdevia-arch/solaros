from __future__ import annotations

from dataclasses import dataclass

from solar_crm.db import connect, query_one


class DeletionBlocked(RuntimeError):
    """Raised when deleting a record would leave an invalid business record."""


@dataclass(frozen=True)
class EntityDefinition:
    table: str
    label: str


ENTITIES: dict[str, EntityDefinition] = {
    "client": EntityDefinition("clients", "cliente"),
    "plant": EntityDefinition("plants", "usina"),
    "beneficiary": EntityDefinition("beneficiaries", "beneficiária"),
    "reading": EntityDefinition("readings", "leitura e dados do relatório"),
    "integration": EntityDefinition("monitoring_integrations", "conta de integração"),
    "plant_integration": EntityDefinition("plant_integrations", "vínculo de monitoramento"),
    "task": EntityDefinition("tasks", "atividade"),
    "ticket": EntityDefinition("tickets", "ocorrência"),
    "invoice": EntityDefinition("invoices", "cobrança"),
    "contract": EntityDefinition("contracts", "contrato de pós-venda"),
    "opportunity": EntityDefinition("opportunities", "oportunidade"),
    "service_order": EntityDefinition("service_orders", "ordem de serviço"),
    "inspection": EntityDefinition("site_inspections", "vistoria"),
    "inspection_photo": EntityDefinition("inspection_photos", "foto da vistoria"),
    "service_contract": EntityDefinition("service_contracts", "contrato de serviço"),
    "pv_module": EntityDefinition("pv_modules", "módulo fotovoltaico"),
    "pv_inverter": EntityDefinition("pv_inverters", "inversor"),
    "sizing_project": EntityDefinition("sizing_projects", "projeto de dimensionamento"),
    "proposal": EntityDefinition("proposals", "proposta/orçamento"),
}


def _count(sql: str, params: tuple[object, ...]) -> int:
    row = query_one(sql, params)
    return int(row["value"] if row else 0)


def _append_count(lines: list[str], count: int, singular: str, plural: str) -> None:
    if count:
        lines.append(f"{count} {singular if count == 1 else plural}")


def deletion_impact(entity: str, record_id: int) -> list[str]:
    """Describe records that cascade, unlink, or disappear with a deletion."""
    if entity not in ENTITIES:
        raise ValueError("Tipo de registro não permitido para exclusão.")

    lines: list[str] = []
    rid = int(record_id)
    if entity == "client":
        summary = query_one(
            """SELECT
               (SELECT COUNT(*) FROM plants WHERE client_id=?) AS plants,
               (SELECT COUNT(*) FROM contracts WHERE client_id=?) AS contracts,
               (SELECT COUNT(*) FROM invoices i JOIN contracts c ON c.id=i.contract_id
                WHERE c.client_id=? AND i.deleted_at IS NULL) AS invoices,
               (SELECT COUNT(*) FROM service_contracts WHERE client_id=?) AS service_contracts,
               (SELECT COUNT(*) FROM service_orders WHERE client_id=?) AS service_orders,
               (SELECT COUNT(*) FROM site_inspections WHERE client_id=?) AS inspections,
               (SELECT COUNT(*) FROM proposals WHERE client_id=?) AS proposals,
               (SELECT COUNT(*) FROM tasks WHERE client_id=?) AS tasks,
               (SELECT COUNT(*) FROM tickets WHERE client_id=?) AS tickets,
               (SELECT COUNT(*) FROM opportunities WHERE client_id=?) AS opportunities,
               (SELECT COUNT(*) FROM sizing_projects WHERE client_id=?) AS sizing_projects""",
            (rid,) * 11,
        ) or {}
        _append_count(lines, int(summary.get("plants", 0)), "usina vinculada", "usinas vinculadas")
        _append_count(lines, int(summary.get("contracts", 0)), "contrato de pós-venda", "contratos de pós-venda")
        _append_count(lines, int(summary.get("invoices", 0)), "cobrança vinculada", "cobranças vinculadas")
        _append_count(lines, int(summary.get("service_contracts", 0)), "contrato de serviço", "contratos de serviço")
        _append_count(lines, int(summary.get("service_orders", 0)), "ordem de serviço", "ordens de serviço")
        _append_count(lines, int(summary.get("inspections", 0)), "vistoria", "vistorias")
        _append_count(lines, int(summary.get("proposals", 0)), "proposta", "propostas")
        _append_count(lines, int(summary.get("tasks", 0)), "atividade", "atividades")
        _append_count(lines, int(summary.get("tickets", 0)), "ocorrência", "ocorrências")
        detached = int(summary.get("opportunities", 0)) + int(summary.get("sizing_projects", 0))
        if detached:
            lines.append(f"{detached} registro(s) comercial/técnico(s) serão preservados sem vínculo com o cliente")
    elif entity == "plant":
        summary = query_one(
            """SELECT
               (SELECT COUNT(*) FROM readings WHERE plant_id=?) AS readings,
               (SELECT COUNT(*) FROM beneficiaries WHERE plant_id=?) AS beneficiaries,
               (SELECT COUNT(*) FROM telemetry_daily WHERE plant_id=?) AS telemetry,
               (SELECT COUNT(*) FROM tasks WHERE plant_id=?) AS tasks,
               (SELECT COUNT(*) FROM tickets WHERE plant_id=?) AS tickets,
               (SELECT COUNT(*) FROM service_orders WHERE plant_id=?) AS service_orders,
               (SELECT COUNT(*) FROM site_inspections WHERE plant_id=?) AS inspections,
               (SELECT COUNT(*) FROM cash_transactions WHERE plant_id=?) AS cash""",
            (rid,) * 8,
        ) or {}
        _append_count(lines, int(summary.get("readings", 0)), "leitura mensal", "leituras mensais")
        _append_count(lines, int(summary.get("beneficiaries", 0)), "beneficiária", "beneficiárias")
        _append_count(lines, int(summary.get("telemetry", 0)), "registro diário de geração", "registros diários de geração")
        _append_count(lines, int(summary.get("tasks", 0)), "atividade", "atividades")
        detached = sum(int(summary.get(key, 0)) for key in ("tickets", "service_orders", "inspections", "cash"))
        if detached:
            lines.append(f"{detached} registro(s) serão preservados, mas ficarão sem vínculo com a usina")
    elif entity == "beneficiary":
        _append_count(lines, _count("SELECT COUNT(*) AS value FROM beneficiary_readings WHERE beneficiary_id=?", (rid,)), "rateio mensal", "rateios mensais")
    elif entity == "reading":
        row = query_one("SELECT plant_id, reference_month FROM readings WHERE id=?", (rid,))
        if row:
            _append_count(
                lines,
                _count("""SELECT COUNT(*) AS value FROM beneficiary_readings br
                           JOIN beneficiaries b ON b.id=br.beneficiary_id
                           WHERE b.plant_id=? AND br.reference_month=?""", (row["plant_id"], row["reference_month"])),
                "rateio de beneficiária",
                "rateios de beneficiárias",
            )
    elif entity == "integration":
        _append_count(lines, _count("SELECT COUNT(*) AS value FROM remote_plants WHERE integration_id=?", (rid,)), "usina remota descoberta", "usinas remotas descobertas")
        _append_count(lines, _count("SELECT COUNT(*) AS value FROM plant_integrations WHERE integration_id=?", (rid,)), "vínculo com usina", "vínculos com usinas")
        _append_count(lines, _count("SELECT COUNT(*) AS value FROM integration_sync_logs WHERE integration_id=?", (rid,)), "histórico de sincronização", "históricos de sincronização")
    elif entity == "contract":
        _append_count(lines, _count("SELECT COUNT(*) AS value FROM invoices WHERE contract_id=? AND deleted_at IS NULL", (rid,)), "cobrança e seu lançamento no caixa", "cobranças e seus lançamentos no caixa")
    elif entity == "invoice":
        _append_count(lines, _count("SELECT COUNT(*) AS value FROM cash_transactions WHERE source_type='invoice' AND source_id=?", (rid,)), "lançamento correspondente no caixa", "lançamentos correspondentes no caixa")
    elif entity == "service_contract":
        _append_count(lines, _count("SELECT COUNT(*) AS value FROM cash_transactions WHERE source_type='service_contract' AND source_id=?", (rid,)), "lançamento correspondente no caixa", "lançamentos correspondentes no caixa")
    elif entity == "service_order":
        _append_count(lines, _count("SELECT COUNT(*) AS value FROM site_inspections WHERE service_order_id=?", (rid,)), "vistoria que será preservada sem vínculo com a O.S.", "vistorias que serão preservadas sem vínculo com a O.S.")
    elif entity == "inspection":
        _append_count(lines, _count("SELECT COUNT(*) AS value FROM inspection_checklist_items WHERE inspection_id=?", (rid,)), "item de checklist", "itens de checklist")
        _append_count(lines, _count("SELECT COUNT(*) AS value FROM inspection_photos WHERE inspection_id=?", (rid,)), "foto", "fotos")
    elif entity == "opportunity":
        _append_count(lines, _count("SELECT COUNT(*) AS value FROM proposals WHERE opportunity_id=?", (rid,)), "proposta que será preservada sem vínculo com a oportunidade", "propostas que serão preservadas sem vínculo com a oportunidade")
    elif entity in {"pv_module", "pv_inverter"}:
        field = "module_id" if entity == "pv_module" else "inverter_id"
        _append_count(lines, _count(f"SELECT COUNT(*) AS value FROM sizing_projects WHERE {field}=?", (rid,)), "projeto que bloqueia a exclusão", "projetos que bloqueiam a exclusão")
    return lines


def delete_record(entity: str, record_id: int) -> None:
    """Delete one allowlisted record and clean non-FK business links atomically."""
    definition = ENTITIES.get(entity)
    if definition is None:
        raise ValueError("Tipo de registro não permitido para exclusão.")

    rid = int(record_id)
    conn = connect()
    try:
        exists = conn.execute(f"SELECT id FROM {definition.table} WHERE id=?", (rid,)).fetchone()
        if not exists:
            raise DeletionBlocked(f"O registro de {definition.label} não existe mais.")

        if entity in {"pv_module", "pv_inverter"}:
            field = "module_id" if entity == "pv_module" else "inverter_id"
            used = conn.execute(f"SELECT COUNT(*) AS value FROM sizing_projects WHERE {field}=?", (rid,)).fetchone()
            count = int(used["value"] if isinstance(used, dict) else used[0])
            if count:
                raise DeletionBlocked(
                    f"Este equipamento está sendo usado em {count} projeto(s). Exclua primeiro os projetos de dimensionamento vinculados."
                )

        if entity == "client":
            conn.execute(
                """DELETE FROM cash_transactions WHERE source_type='invoice' AND source_id IN
                   (SELECT i.id FROM invoices i JOIN contracts c ON c.id=i.contract_id WHERE c.client_id=?)""",
                (rid,),
            )
            conn.execute(
                """DELETE FROM cash_transactions WHERE source_type='service_contract' AND source_id IN
                   (SELECT id FROM service_contracts WHERE client_id=?)""",
                (rid,),
            )
        elif entity == "contract":
            conn.execute(
                """DELETE FROM cash_transactions WHERE source_type='invoice' AND source_id IN
                   (SELECT id FROM invoices WHERE contract_id=?)""",
                (rid,),
            )
        elif entity == "invoice":
            conn.execute("DELETE FROM cash_transactions WHERE source_type='invoice' AND source_id=?", (rid,))
        elif entity == "service_contract":
            conn.execute("DELETE FROM cash_transactions WHERE source_type='service_contract' AND source_id=?", (rid,))
        elif entity == "reading":
            reading = conn.execute("SELECT plant_id, reference_month FROM readings WHERE id=?", (rid,)).fetchone()
            plant_id = reading["plant_id"] if isinstance(reading, dict) else reading[0]
            reference_month = reading["reference_month"] if isinstance(reading, dict) else reading[1]
            conn.execute(
                """DELETE FROM beneficiary_readings WHERE reference_month=? AND beneficiary_id IN
                   (SELECT id FROM beneficiaries WHERE plant_id=?)""",
                (reference_month, plant_id),
            )

        if entity == "invoice":
            conn.execute("UPDATE invoices SET deleted_at=CURRENT_TIMESTAMP WHERE id=?", (rid,))
        else:
            conn.execute(f"DELETE FROM {definition.table} WHERE id=?", (rid,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
