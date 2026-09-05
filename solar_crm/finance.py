from __future__ import annotations

from solar_crm.db import execute, query_one


def _invoice_cash_status(status: str) -> str:
    if status == "Pago":
        return "Recebido"
    if status == "Cancelado":
        return "Cancelado"
    return "A receber"


def sync_invoice_to_cash(invoice_id: int) -> int:
    """Create or refresh the cash entry linked to a contract invoice."""
    invoice = query_one(
        """SELECT i.*, c.client_id, c.plan, c.scope, c.billing_cycle
           FROM invoices i JOIN contracts c ON c.id=i.contract_id
           WHERE i.id=?""",
        (invoice_id,),
    )
    if not invoice:
        raise ValueError("Cobrança não encontrada para lançamento no caixa.")
    category = (
        "Consultoria e mentoria"
        if invoice["billing_cycle"] == "Parcela única"
        else "Mensalidade pós-venda"
    )
    return execute(
        """INSERT INTO cash_transactions
           (transaction_type, category, client_id, plant_id, competence_month, issue_date,
            due_date, settlement_date, amount, status, payment_method, document_number,
            description, notes, source_type, source_id)
           VALUES ('Receita', ?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 'invoice', ?)
           ON CONFLICT(source_type, source_id) DO UPDATE SET
             category=excluded.category, client_id=excluded.client_id,
             competence_month=excluded.competence_month, issue_date=excluded.issue_date,
             due_date=excluded.due_date, settlement_date=excluded.settlement_date,
             amount=excluded.amount, status=excluded.status,
             document_number=excluded.document_number, description=excluded.description,
             notes=excluded.notes""",
        (
            category,
            invoice["client_id"],
            invoice["reference_month"],
            invoice["reference_month"],
            invoice["due_date"],
            invoice.get("paid_at"),
            float(invoice["amount"] or 0),
            _invoice_cash_status(invoice["status"]),
            f"FAT-{invoice_id}",
            invoice["plan"],
            invoice.get("notes") or invoice.get("scope") or "",
            invoice_id,
        ),
    )


def sync_service_contract_to_cash(contract_id: int) -> int:
    """Create the receivable corresponding to a generated service contract."""
    contract = query_one("SELECT * FROM service_contracts WHERE id=?", (contract_id,))
    if not contract:
        raise ValueError("Contrato não encontrado para lançamento no caixa.")
    amount = float(contract["amount"] or 0)
    if amount <= 0:
        return 0
    competence = f"{str(contract['start_date'])[:7]}-01"
    status = "Cancelado" if contract["status"] == "Cancelado" else "A receber"
    return execute(
        """INSERT INTO cash_transactions
           (transaction_type, category, client_id, plant_id, competence_month, issue_date,
            due_date, settlement_date, amount, status, payment_method, document_number,
            description, notes, source_type, source_id)
           VALUES ('Receita', 'Contratos de serviço', ?, NULL, ?, ?, ?, NULL, ?, ?, NULL,
                   ?, ?, ?, 'service_contract', ?)
           ON CONFLICT(source_type, source_id) DO UPDATE SET
             client_id=excluded.client_id, competence_month=excluded.competence_month,
             issue_date=excluded.issue_date, due_date=excluded.due_date,
             amount=excluded.amount, status=excluded.status,
             document_number=excluded.document_number, description=excluded.description,
             notes=excluded.notes""",
        (
            contract["client_id"],
            competence,
            contract["start_date"],
            contract["start_date"],
            amount,
            status,
            contract["number"],
            contract["title"],
            contract.get("payment_terms") or contract.get("scope") or "",
            contract_id,
        ),
    )


def update_service_contract_cash_status(contract_id: int, contract_status: str) -> None:
    """Keep cancellation state aligned without overwriting user-edited cash details."""
    if contract_status == "Cancelado":
        execute(
            """UPDATE cash_transactions
               SET status='Cancelado', settlement_date=NULL
               WHERE source_type='service_contract' AND source_id=?""",
            (contract_id,),
        )
    else:
        execute(
            """UPDATE cash_transactions
               SET status='A receber'
               WHERE source_type='service_contract' AND source_id=? AND status='Cancelado'""",
            (contract_id,),
        )
