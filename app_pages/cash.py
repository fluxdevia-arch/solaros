from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from solar_crm.calculations import money
from solar_crm.db import execute, query, query_df
from solar_crm.ui import date_br, flash, month_label, page_intro, show_flash


REVENUE_CATEGORIES = [
    "Consultoria e mentoria",
    "Contratos de serviço",
    "Manutenção corretiva",
    "Manutenção preventiva",
    "Limpeza de módulos",
    "Visita técnica",
    "Venda de peças",
    "Mensalidade pós-venda",
    "Instalação ou ampliação",
    "Outras receitas",
]
EXPENSE_CATEGORIES = [
    "Materiais e peças",
    "Deslocamento",
    "Mão de obra terceirizada",
    "Ferramentas e equipamentos",
    "Softwares",
    "Impostos e taxas",
    "Outras despesas",
]
MAINTENANCE_CATEGORIES = [
    "Manutenção corretiva",
    "Manutenção preventiva",
    "Limpeza de módulos",
    "Visita técnica",
    "Venda de peças",
]


def _date_value(value, fallback=None):
    if value is None or pd.isna(value) or str(value).strip() == "":
        return fallback
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return fallback


def _text_value(value) -> str:
    return "" if value is None or pd.isna(value) else str(value)


page_intro("Registre faturamento de manutenção, receitas recorrentes, despesas, recebimentos e compromissos do caixa.")
show_flash()

clients = query("SELECT id, name FROM clients WHERE status='Ativo' ORDER BY name")
all_clients = query("SELECT id, name, status FROM clients ORDER BY name")
plants = query(
    """SELECT p.id, p.name, c.name AS client_name
       FROM plants p JOIN clients c ON c.id=p.client_id
       WHERE p.status!='Desativada' ORDER BY c.name, p.name"""
)
all_plants = query(
    """SELECT p.id, p.name, p.status, c.name AS client_name
       FROM plants p JOIN clients c ON c.id=p.client_id ORDER BY c.name, p.name"""
)
client_map = {"Sem cliente vinculado": None, **{row["name"]: row["id"] for row in clients}}
plant_map = {"Sem usina vinculada": None, **{f"{row['name']} · {row['client_name']}": row["id"] for row in plants}}

months = query("SELECT DISTINCT competence_month FROM cash_transactions ORDER BY competence_month DESC")
current_month = date.today().replace(day=1).isoformat()
month_values = [row["competence_month"] for row in months]
if current_month not in month_values:
    month_values.insert(0, current_month)

with st.container(horizontal=True, horizontal_alignment="right"):
    new_entry = st.popover("Novo lançamento", icon=":material/add_card:")

with new_entry:
    transaction_type = st.segmented_control("Tipo", ["Receita", "Despesa"], default="Receita", key="cash_type")
    categories = REVENUE_CATEGORIES if transaction_type == "Receita" else EXPENSE_CATEGORIES
    with st.form("cash_entry_form", clear_on_submit=True):
        category = st.selectbox("Categoria", categories)
        description = st.text_input("Descrição", placeholder="Ex.: manutenção preventiva do inversor")
        c1, c2 = st.columns(2)
        client_label = c1.selectbox("Cliente", list(client_map))
        plant_label = c2.selectbox("Usina", list(plant_map))
        amount = c1.number_input("Valor (R$)", min_value=0.01, value=350.0, step=10.0)
        competence = c2.date_input("Competência", value=date.today().replace(day=1))
        issue_date = c1.date_input("Data de emissão", value=date.today())
        due_date = c2.date_input("Vencimento", value=date.today())
        status_options = ["Recebido", "A receber", "Cancelado"] if transaction_type == "Receita" else ["Pago", "A pagar", "Cancelado"]
        status = c1.selectbox("Status", status_options, index=1)
        settlement_date = c2.date_input("Data do recebimento/pagamento", value=None)
        payment_method = c1.selectbox("Forma de pagamento", ["Pix", "Boleto", "Transferência", "Cartão", "Dinheiro", "Outro"])
        document_number = c2.text_input("Nº da OS, NF ou recibo")
        notes = st.text_area("Observações")
        submitted = st.form_submit_button("Salvar lançamento", type="primary", icon=":material/save:")
        if submitted:
            if not description.strip():
                st.error("Informe uma descrição para o lançamento.")
            else:
                final_settlement = settlement_date
                if status in ("Recebido", "Pago") and final_settlement is None:
                    final_settlement = date.today()
                execute(
                    """INSERT INTO cash_transactions
                       (transaction_type, category, client_id, plant_id, competence_month, issue_date,
                        due_date, settlement_date, amount, status, payment_method, document_number,
                        description, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        transaction_type, category, client_map[client_label], plant_map[plant_label],
                        competence.replace(day=1).isoformat(), issue_date.isoformat(), due_date.isoformat(),
                        final_settlement.isoformat() if final_settlement else None, amount, status,
                        payment_method, document_number.strip(), description.strip(), notes.strip(),
                    ),
                )
                flash("Lançamento incluído no caixa.")
                st.rerun()

selected_month = st.selectbox("Mês de competência", month_values, format_func=month_label, key="cash_month")

summary = query_df(
    """SELECT
           COALESCE(SUM(CASE WHEN transaction_type='Receita' AND status='Recebido' THEN amount ELSE 0 END),0) AS received,
           COALESCE(SUM(CASE WHEN transaction_type='Despesa' AND status='Pago' THEN amount ELSE 0 END),0) AS paid,
           COALESCE(SUM(CASE WHEN transaction_type='Receita' AND status='A receber' THEN amount ELSE 0 END),0) AS receivable,
           COALESCE(SUM(CASE WHEN transaction_type='Despesa' AND status='A pagar' THEN amount ELSE 0 END),0) AS payable,
           COALESCE(SUM(CASE WHEN transaction_type='Receita' AND category IN ('Manutenção corretiva','Manutenção preventiva','Limpeza de módulos','Visita técnica','Venda de peças') AND status!='Cancelado' THEN amount ELSE 0 END),0) AS maintenance_revenue
       FROM cash_transactions WHERE competence_month=?""",
    (selected_month,),
).iloc[0]

with st.container(horizontal=True):
    st.metric("Recebido", money(summary["received"]), border=True)
    st.metric("Pago", money(summary["paid"]), border=True)
    st.metric("Saldo realizado", money(summary["received"] - summary["paid"]), border=True)
    st.metric("A receber", money(summary["receivable"]), border=True)
    st.metric("A pagar", money(summary["payable"]), border=True)
    st.metric("Faturamento manutenção", money(summary["maintenance_revenue"]), border=True)

transactions_tab, maintenance_tab, flow_tab = st.tabs([
    ":material/receipt_long: Movimentações",
    ":material/build: Manutenções faturadas",
    ":material/monitoring: Fluxo mensal",
])

transactions = query_df(
    """SELECT ct.id, ct.client_id, ct.plant_id, ct.competence_month,
              ct.issue_date, ct.due_date,
              ct.settlement_date, ct.transaction_type,
              ct.category, ct.description, ct.amount, ct.status, ct.payment_method,
              ct.document_number, ct.notes, ct.source_type, ct.source_id,
              COALESCE(c.name,'-') AS client, COALESCE(p.name,'-') AS plant,
              CASE WHEN ct.source_type='invoice' THEN 'Cobrança de contrato'
                   WHEN ct.source_type='service_contract' THEN 'Contrato de serviço'
                   ELSE 'Lançamento manual' END AS source
       FROM cash_transactions ct
       LEFT JOIN clients c ON c.id=ct.client_id
       LEFT JOIN plants p ON p.id=ct.plant_id
       WHERE ct.competence_month=? ORDER BY ct.due_date DESC, ct.id DESC""",
    (selected_month,),
)

with transactions_tab:
    if transactions.empty:
        st.info("Nenhum lançamento registrado neste mês.", icon=":material/info:")
    else:
        display = transactions[[
            "id", "issue_date", "due_date", "settlement_date", "transaction_type",
            "category", "description", "amount", "status", "payment_method",
            "document_number", "client", "plant", "source",
        ]].rename(columns={
            "id": "ID", "issue_date": "Emissão", "due_date": "Vencimento",
            "settlement_date": "Baixa", "transaction_type": "Tipo", "category": "Categoria",
            "description": "Descrição", "amount": "Valor", "status": "Status",
            "payment_method": "Pagamento", "document_number": "Documento",
            "client": "Cliente", "plant": "Usina", "source": "Origem",
        })
        for column in ["Emissão", "Vencimento", "Baixa"]:
            display[column] = display[column].map(date_br)
        st.dataframe(
            display,
            hide_index=True,
            column_config={
                "ID": st.column_config.NumberColumn(width="small"),
                "Descrição": st.column_config.TextColumn(pinned=True),
                "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )
        st.download_button(
            "Exportar movimentações",
            display.to_csv(index=False).encode("utf-8-sig"),
            f"caixa_{selected_month[:7]}.csv",
            "text/csv",
            icon=":material/download:",
        )

        with st.expander("Editar lançamento", icon=":material/edit:"):
            edit_labels = {
                f"#{int(row.id)} · {row.description} · {money(row.amount)}": int(row.id)
                for row in transactions.itertuples()
            }
            edit_label = st.selectbox(
                "Lançamento para editar", list(edit_labels), key="cash_edit_entry"
            )
            edit_id = edit_labels[edit_label]
            edit_row = transactions.loc[transactions["id"] == edit_id].iloc[0]
            edit_type = str(edit_row["transaction_type"])
            edit_categories = list(REVENUE_CATEGORIES if edit_type == "Receita" else EXPENSE_CATEGORIES)
            current_category = str(edit_row["category"])
            if current_category not in edit_categories:
                edit_categories.append(current_category)

            edit_client_ids = [None, *[int(row["id"]) for row in all_clients]]
            edit_client_names = {
                None: "Sem cliente vinculado",
                **{
                    int(row["id"]): f"{row['name']}" + (" · Inativo" if row["status"] != "Ativo" else "")
                    for row in all_clients
                },
            }
            edit_plant_ids = [None, *[int(row["id"]) for row in all_plants]]
            edit_plant_names = {
                None: "Sem usina vinculada",
                **{
                    int(row["id"]): f"{row['name']} · {row['client_name']}"
                    + (" · Desativada" if row["status"] == "Desativada" else "")
                    for row in all_plants
                },
            }
            current_client_id = None if pd.isna(edit_row["client_id"]) else int(edit_row["client_id"])
            current_plant_id = None if pd.isna(edit_row["plant_id"]) else int(edit_row["plant_id"])
            edit_status_options = (
                ["Recebido", "A receber", "Cancelado"]
                if edit_type == "Receita"
                else ["Pago", "A pagar", "Cancelado"]
            )
            current_status = str(edit_row["status"])
            if current_status not in edit_status_options:
                edit_status_options.append(current_status)
            payment_options = ["Não informado", "Pix", "Boleto", "Transferência", "Cartão", "Dinheiro", "Outro"]
            current_payment = _text_value(edit_row["payment_method"]) or "Não informado"
            if current_payment not in payment_options:
                payment_options.append(current_payment)

            st.caption(
                f"Tipo: {edit_type} · Origem: {edit_row['source']}. "
                "A edição financeira não altera o texto do contrato original."
            )
            with st.form("cash_edit_form"):
                edit_category = st.selectbox(
                    "Categoria",
                    edit_categories,
                    index=edit_categories.index(current_category),
                    key="cash_edit_category",
                )
                edit_description = st.text_input(
                    "Descrição", value=str(edit_row["description"]), key="cash_edit_description"
                )
                e1, e2 = st.columns(2)
                edit_client_id = e1.selectbox(
                    "Cliente",
                    edit_client_ids,
                    index=edit_client_ids.index(current_client_id),
                    format_func=lambda value: edit_client_names[value],
                    key="cash_edit_client",
                )
                edit_plant_id = e2.selectbox(
                    "Usina",
                    edit_plant_ids,
                    index=edit_plant_ids.index(current_plant_id),
                    format_func=lambda value: edit_plant_names[value],
                    key="cash_edit_plant",
                )
                edit_amount = e1.number_input(
                    "Valor (R$)", min_value=0.01, value=float(edit_row["amount"]), step=10.0,
                    key="cash_edit_amount",
                )
                edit_competence = e2.date_input(
                    "Competência",
                    value=_date_value(edit_row["competence_month"], date.today().replace(day=1)),
                    key="cash_edit_competence",
                )
                edit_issue = e1.date_input(
                    "Data de emissão", value=_date_value(edit_row["issue_date"], date.today()),
                    key="cash_edit_issue",
                )
                edit_due = e2.date_input(
                    "Vencimento", value=_date_value(edit_row["due_date"], date.today()),
                    key="cash_edit_due",
                )
                edit_status = e1.selectbox(
                    "Status", edit_status_options, index=edit_status_options.index(current_status),
                    key="cash_edit_status",
                )
                edit_settlement = e2.date_input(
                    "Data do recebimento/pagamento",
                    value=_date_value(edit_row["settlement_date"]),
                    key="cash_edit_settlement",
                )
                edit_payment = e1.selectbox(
                    "Forma de pagamento", payment_options,
                    index=payment_options.index(current_payment), key="cash_edit_payment",
                )
                edit_document = e2.text_input(
                    "Nº da OS, NF, recibo ou contrato",
                    value=_text_value(edit_row["document_number"]), key="cash_edit_document",
                )
                edit_notes = st.text_area(
                    "Observações", value=_text_value(edit_row["notes"]), key="cash_edit_notes"
                )
                save_edit = st.form_submit_button(
                    "Salvar alterações", type="primary", icon=":material/save:",
                    key="cash_edit_submit",
                )
            if save_edit:
                if not edit_description.strip():
                    st.error("Informe uma descrição para o lançamento.")
                else:
                    final_settlement = edit_settlement
                    if edit_status in ("Recebido", "Pago") and final_settlement is None:
                        final_settlement = date.today()
                    if edit_status not in ("Recebido", "Pago"):
                        final_settlement = None
                    execute(
                        """UPDATE cash_transactions
                           SET category=?, client_id=?, plant_id=?, competence_month=?, issue_date=?,
                               due_date=?, settlement_date=?, amount=?, status=?, payment_method=?,
                               document_number=?, description=?, notes=?
                           WHERE id=?""",
                        (
                            edit_category, edit_client_id, edit_plant_id,
                            edit_competence.replace(day=1).isoformat(), edit_issue.isoformat(),
                            edit_due.isoformat(), final_settlement.isoformat() if final_settlement else None,
                            edit_amount, edit_status,
                            None if edit_payment == "Não informado" else edit_payment,
                            edit_document.strip(), edit_description.strip(), edit_notes.strip(), edit_id,
                        ),
                    )
                    flash("Lançamento atualizado no caixa.")
                    st.rerun()

        open_rows = transactions[transactions["status"].isin(["A receber", "A pagar"])]
        if not open_rows.empty:
            with st.expander("Dar baixa em lançamento", icon=":material/check_circle:"):
                labels = {
                    f"#{row.id} · {row.description} · {money(row.amount)}": (int(row.id), row.transaction_type)
                    for row in open_rows.itertuples()
                }
                selected = st.selectbox("Lançamento", list(labels), key="cash_settlement_entry")
                settlement = st.date_input("Data da baixa", value=date.today(), key="cash_settlement_date")
                if st.button("Confirmar baixa", type="primary", icon=":material/done_all:"):
                    transaction_id, row_type = labels[selected]
                    new_status = "Recebido" if row_type == "Receita" else "Pago"
                    execute(
                        "UPDATE cash_transactions SET status=?, settlement_date=? WHERE id=?",
                        (new_status, settlement.isoformat(), transaction_id),
                    )
                    flash("Baixa registrada no caixa.")
                    st.rerun()

with maintenance_tab:
    maintenance = transactions[
        (transactions["transaction_type"] == "Receita")
        & (transactions["category"].isin(MAINTENANCE_CATEGORIES))
        & (transactions["status"] != "Cancelado")
    ].copy()
    if maintenance.empty:
        st.info("Nenhum faturamento de manutenção neste mês.", icon=":material/build:")
    else:
        with st.container(horizontal=True):
            st.metric("Serviços faturados", len(maintenance), border=True)
            st.metric("Valor faturado", money(maintenance["amount"].sum()), border=True)
            st.metric("Já recebido", money(maintenance.loc[maintenance["status"] == "Recebido", "amount"].sum()), border=True)
        chart_data = maintenance.groupby("category", as_index=False)["amount"].sum().rename(columns={"category": "Serviço", "amount": "Faturamento"})
        chart = alt.Chart(chart_data).mark_bar().encode(
            x=alt.X("Faturamento:Q", title="Faturamento (R$)"),
            y=alt.Y("Serviço:N", title=None, sort="-x"),
            tooltip=["Serviço", alt.Tooltip("Faturamento:Q", format=".2f")],
        )
        st.altair_chart(chart)
        maintenance_display = maintenance[["description", "client", "plant", "amount", "status", "document_number"]].rename(columns={
            "description": "Serviço", "client": "Cliente", "plant": "Usina",
            "amount": "Valor", "status": "Status", "document_number": "OS/NF/recibo",
        })
        st.dataframe(maintenance_display, hide_index=True, column_config={"Serviço": st.column_config.TextColumn(pinned=True), "Valor": st.column_config.NumberColumn(format="R$ %.2f")})

with flow_tab:
    flow = query_df(
        """SELECT competence_month AS month,
                  SUM(CASE WHEN transaction_type='Receita' AND status='Recebido' THEN amount ELSE 0 END) AS revenue,
                  SUM(CASE WHEN transaction_type='Despesa' AND status='Pago' THEN amount ELSE 0 END) AS expense
           FROM cash_transactions GROUP BY competence_month ORDER BY competence_month"""
    )
    if flow.empty:
        st.info("O histórico aparecerá após os primeiros lançamentos.")
    else:
        flow["Saldo"] = flow["revenue"] - flow["expense"]
        flow["Mês"] = flow["month"].map(month_label)
        chart_data = flow.melt(id_vars=["Mês"], value_vars=["revenue", "expense"], var_name="Tipo", value_name="Valor")
        chart_data["Tipo"] = chart_data["Tipo"].map({"revenue": "Recebido", "expense": "Pago"})
        st.bar_chart(chart_data, x="Mês", y="Valor", color="Tipo", x_label=None, y_label="R$")
        st.dataframe(
            flow[["Mês", "revenue", "expense", "Saldo"]].rename(columns={"revenue": "Recebido", "expense": "Pago"}),
            hide_index=True,
            column_config={
                "Recebido": st.column_config.NumberColumn(format="R$ %.2f"),
                "Pago": st.column_config.NumberColumn(format="R$ %.2f"),
                "Saldo": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )

st.caption("O caixa é gerencial. A emissão de nota fiscal e as obrigações contábeis continuam no sistema fiscal da empresa.")
