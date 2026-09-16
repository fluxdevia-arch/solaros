from __future__ import annotations

import copy
import re

import pandas as pd
import streamlit as st

from solar_crm.calculations import number_br
from solar_crm.compensation_documents import generate_compensation_statement_pdf
from solar_crm.compensation_statement import CompensationStatementError, analyze_compensation_statement
from solar_crm.db import query
from solar_crm.ui import page_intro


@st.cache_data(ttl="1h", max_entries=24, show_spinner=False)
def _analyze_pdf(content: bytes, filename: str):
    return analyze_compensation_statement(content, filename)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "demonstrativo"


page_intro(
    "Envie o Demonstrativo de Compensação de Energia da Energisa para entender a injeção, o rateio, os créditos, as unidades beneficiárias e o histórico da geradora."
)

with st.container(border=True):
    st.subheader("Demonstrativo para análise", icon=":material/upload_file:")
    uploaded = st.file_uploader(
        "Arquivo PDF do demonstrativo de compensação",
        type=["pdf"],
        help="Use o PDF original emitido pela Energisa. O arquivo não é salvo automaticamente.",
        key="compensation_statement_pdf",
    )
    st.caption("O leitor reconhece os postos ponta, fora de ponta, convencional e intermediário, além das classes GD I, GD II e GD III.")

if uploaded is None:
    st.info("Envie o demonstrativo para gerar a leitura explicada e o relatório em PDF.", icon=":material/energy_savings_leaf:")
    st.stop()

try:
    with st.spinner("Lendo histórico, movimentações, rateio e validade dos créditos..."):
        original = _analyze_pdf(uploaded.getvalue(), uploaded.name)
except CompensationStatementError as exc:
    st.error(str(exc), icon=":material/error:")
    st.stop()
except Exception:
    st.error("Não foi possível interpretar este arquivo. Confirme se é o PDF original da Energisa.", icon=":material/error:")
    st.stop()

statement = copy.deepcopy(original)
beneficiaries = query("SELECT name, holder_name, unit_code FROM beneficiaries")
beneficiary_map = {_digits(row["unit_code"]): row for row in beneficiaries}
for transfer in statement.transfers:
    saved = beneficiary_map.get(_digits(transfer.unit_code))
    if saved:
        transfer.beneficiary_name = saved["name"] or saved["holder_name"] or ""

st.success(
    f"Demonstrativo reconhecido: UC geradora {statement.unit_code or 'não identificada'} · {len(statement.transfers)} beneficiária(s).",
    icon=":material/check_circle:",
)

with st.expander("Conferir os dados do relatório", icon=":material/edit:"):
    left, right = st.columns(2)
    with left:
        statement.client_name = st.text_input("Cliente / titular", value=statement.client_name, key="comp_client")
        statement.address = st.text_input("Endereço da unidade", value=statement.address, key="comp_address")
        statement.unit_code = st.text_input("UC geradora", value=statement.unit_code, key="comp_unit")
    with right:
        statement.voltage_group = st.text_input("Grupo / modalidade", value=statement.voltage_group, key="comp_voltage")
        statement.reference_month = st.text_input("Competência (AAAA-MM)", value=statement.reference_month, key="comp_reference")
        statement.utility = st.text_input("Distribuidora", value=statement.utility, key="comp_utility")

with st.container(horizontal=True):
    st.metric("Injetada no ciclo", f"{number_br(statement.injected_kwh, 0)} kWh", border=True)
    st.metric("Enviada às beneficiárias", f"{number_br(statement.allocated_kwh, 0)} kWh", border=True)
    st.metric("Compensada na geradora", f"{number_br(statement.compensated_kwh, 0)} kWh", border=True)
    st.metric("Crédito disponível", f"{number_br(statement.available_credit_kwh, 0)} kWh", border=True)
    st.metric("Crédito expirado", f"{number_br(statement.expired_kwh, 0)} kWh", border=True)

st.subheader("O que aconteceu neste ciclo", icon=":material/lightbulb:")
st.info(
    f"A geradora injetou {number_br(statement.injected_kwh, 0)} kWh na rede. "
    f"A Energisa transferiu {number_br(statement.allocated_kwh, 0)} kWh para {len(statement.transfers)} unidade(s) beneficiária(s), "
    f"usou {number_br(statement.compensated_kwh, 0)} kWh para compensar o consumo da própria geradora "
    f"e manteve {number_br(statement.available_credit_kwh, 0)} kWh disponíveis ao final do ciclo.",
    icon=":material/energy_savings_leaf:",
)

st.subheader("Distribuição entre as unidades", icon=":material/account_tree:")
transfer_frame = pd.DataFrame([{
    "Rateio (%)": transfer.allocation_pct,
    "UC beneficiária": transfer.unit_code,
    "Nome no cadastro": transfer.beneficiary_name or "Não vinculada",
    "Convencional (kWh)": transfer.conventional_kwh,
    "Ponta (kWh)": transfer.peak_kwh,
    "Fora de ponta (kWh)": transfer.off_peak_kwh,
    "Intermediário (kWh)": transfer.intermediate_kwh,
    "Total enviado (kWh)": transfer.total_kwh,
} for transfer in statement.transfers])
if transfer_frame.empty:
    st.warning("Nenhuma transferência foi identificada no arquivo.")
else:
    st.dataframe(
        transfer_frame,
        hide_index=True,
        column_config={
            "Rateio (%)": st.column_config.NumberColumn(format="%.1f%%"),
            "Convencional (kWh)": st.column_config.NumberColumn(format="%.0f"),
            "Ponta (kWh)": st.column_config.NumberColumn(format="%.0f"),
            "Fora de ponta (kWh)": st.column_config.NumberColumn(format="%.0f"),
            "Intermediário (kWh)": st.column_config.NumberColumn(format="%.0f"),
            "Total enviado (kWh)": st.column_config.NumberColumn(format="%.0f"),
        },
    )
    allocated_pct = sum(item.allocation_pct for item in statement.transfers)
    if abs(allocated_pct - 100) <= 0.1 and abs(statement.allocated_kwh - statement.transferred_kwh) <= 1:
        st.success(
            f"Rateio conferido: {number_br(allocated_pct, 1)}% e {number_br(statement.allocated_kwh, 0)} kWh discriminados, iguais ao total transferido.",
            icon=":material/check_circle:",
        )
    else:
        st.warning("Revise o rateio: o percentual ou a energia discriminada não fecha com o total transferido.")

off_peak = sorted((row for row in statement.history if row.period == "Fora de ponta"), key=lambda row: (row.year, row.month))
if off_peak:
    st.subheader("Histórico da energia injetada", icon=":material/bar_chart:")
    history_frame = pd.DataFrame({
        "Competência": [f"{row.month:02d}/{row.year}" for row in off_peak],
        "Energia injetada (kWh)": [row.injected_kwh for row in off_peak],
    })
    st.bar_chart(history_frame, x="Competência", y="Energia injetada (kWh)", color="#2A6F97")

with st.expander("Movimentação detalhada dos créditos", icon=":material/table_view:"):
    movement_frame = pd.DataFrame([{
        "Posto": row.period, "Classe": row.generation_class, "Saldo anterior (kWh)": row.previous_balance_kwh,
        "Injetado (kWh)": row.injected_kwh, "Recebido (kWh)": row.received_kwh,
        "Compensado (kWh)": row.compensated_kwh, "Transferido (kWh)": row.transferred_kwh,
        "Expirado (kWh)": row.expired_kwh, "Disponível (kWh)": row.available_kwh,
    } for row in statement.movements])
    st.dataframe(movement_frame, hide_index=True)

with st.expander("Origem e validade do saldo anterior", icon=":material/history:"):
    credit_frame = pd.DataFrame([{
        "Origem": f"{row.month:02d}/{row.year}", "Posto": row.period,
        "Saldo anterior (kWh)": row.previous_balance_kwh, "Compensado / ajustado (kWh)": row.compensated_kwh,
        "Disponível (kWh)": row.available_kwh, "Validade": row.expiration,
    } for row in statement.credits if row.available_kwh > 0])
    st.dataframe(credit_frame, hide_index=True)

for warning in statement.warnings:
    st.warning(warning)

pdf = generate_compensation_statement_pdf(statement)
filename = f"relatorio-compensacao-{_slug(statement.unit_code)}-{_slug(statement.reference_month)}.pdf"
st.download_button(
    "Baixar relatório explicado em PDF", data=pdf, file_name=filename,
    mime="application/pdf", type="primary", icon=":material/picture_as_pdf:",
)
st.caption(
    "O relatório interpreta os dados declarados pela distribuidora. Para auditoria completa, compare também as faturas das beneficiárias e o monitoramento do inversor."
)
