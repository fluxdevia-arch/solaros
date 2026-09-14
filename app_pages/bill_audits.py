from __future__ import annotations

import copy
import re

import pandas as pd
import streamlit as st

from solar_crm.bill_audit import BillAuditError, analyze_energisa_bill, items_as_rows, recalculate_audit
from solar_crm.bill_audit_documents import generate_bill_audit_pdf
from solar_crm.calculations import money, number_br
from solar_crm.ui import page_intro


@st.cache_data(ttl="1h", max_entries=24, show_spinner=False)
def _analyze_pdf(content: bytes, filename: str):
    return analyze_energisa_bill(content, filename)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "fatura"


page_intro(
    "Envie a fatura original da Energisa para conferir consumo, injeção, compensação, tributos, Fio B, economia e oportunidades de correção."
)

with st.container(border=True):
    st.subheader("Fatura para auditoria", icon=":material/upload_file:")
    uploaded = st.file_uploader(
        "Arquivo PDF da Energisa",
        type=["pdf"],
        help="Use o PDF original baixado do portal. O arquivo é processado apenas para gerar a análise e não é salvo automaticamente.",
        key="energisa_bill_pdf",
    )
    st.caption("Compatível com unidades geradoras do Grupo A, geradoras em baixa tensão e unidades beneficiárias.")

if uploaded is None:
    st.info("Envie uma fatura para iniciar a auditoria automática.", icon=":material/receipt_long:")
    st.stop()

try:
    with st.spinner("Lendo itens, medições, créditos e tributos da fatura..."):
        original_audit = _analyze_pdf(uploaded.getvalue(), uploaded.name)
except BillAuditError as exc:
    st.error(str(exc), icon=":material/error:")
    st.stop()
except Exception:
    st.error(
        "Não foi possível interpretar esta fatura. Confirme se é o PDF original da Energisa e tente novamente.",
        icon=":material/error:",
    )
    st.stop()

audit = copy.deepcopy(original_audit)
st.success(
    f"Fatura reconhecida: {audit.unit_profile} - UC {audit.unit_code or 'não identificada'}.",
    icon=":material/check_circle:",
)

with st.expander("Conferir e corrigir dados extraídos", icon=":material/edit:"):
    st.caption("Revise os campos antes de baixar o laudo. As correções feitas aqui serão usadas no PDF.")
    left, right = st.columns(2)
    with left:
        audit.client_name = st.text_input("Cliente", value=audit.client_name, key="bill_client_name")
        audit.address = st.text_input("Endereço da unidade", value=audit.address, key="bill_address")
        audit.unit_code = st.text_input("Unidade consumidora", value=audit.unit_code, key="bill_unit_code")
        profiles = ["Geradora - Grupo A", "Geradora - baixa tensão", "Unidade beneficiária", "Grupo A", "Não identificado"]
        if audit.unit_profile not in profiles:
            profiles.insert(0, audit.unit_profile)
        audit.unit_profile = st.selectbox(
            "Tipo da unidade",
            profiles,
            index=profiles.index(audit.unit_profile),
            key="bill_unit_profile",
        )
        audit.reference_month = st.text_input("Mês de referência (AAAA-MM)", value=audit.reference_month, key="bill_reference")
        audit.due_date = st.text_input("Vencimento", value=audit.due_date, key="bill_due")
    with right:
        audit.invoice_amount = st.number_input("Valor faturado (R$)", min_value=0.0, value=float(audit.invoice_amount), step=1.0, key="bill_amount")
        audit.consumption_kwh = st.number_input("Energia medida consumida (kWh)", min_value=0.0, value=float(audit.consumption_kwh), step=1.0, key="bill_consumed")
        has_measured_injection = st.checkbox(
            "A fatura informa energia injetada medida",
            value=audit.injected_measured_kwh is not None,
            key="bill_has_injection",
        )
        measured_default = float(audit.injected_measured_kwh or 0.0)
        measured_injection = st.number_input(
            "Energia injetada medida (kWh)",
            min_value=0.0,
            value=measured_default,
            step=1.0,
            disabled=not has_measured_injection,
            key="bill_injected",
        )
        audit.injected_measured_kwh = float(measured_injection) if has_measured_injection else None
        audit.compensated_kwh = st.number_input("Energia compensada (kWh)", min_value=0.0, value=float(audit.compensated_kwh), step=1.0, key="bill_compensated")
        audit.credit_balance_kwh = st.number_input("Saldo de créditos (kWh)", min_value=0.0, value=float(audit.credit_balance_kwh), step=1.0, key="bill_credit_balance")

    st.markdown("##### Valores financeiros conferidos")
    c1, c2, c3, c4 = st.columns(4)
    audit.solar_credit_value = c1.number_input("Créditos solares (R$)", min_value=0.0, value=float(audit.solar_credit_value), step=1.0, key="bill_solar_credit")
    audit.fio_b_value = c2.number_input("Fio B / ajuste GD II (R$)", min_value=0.0, value=float(audit.fio_b_value), step=1.0, key="bill_fio_b")
    audit.icms_value = c3.number_input("ICMS (R$)", min_value=0.0, value=float(audit.icms_value), step=1.0, key="bill_icms")
    audit.icms_base = c4.number_input("Base do ICMS (R$)", min_value=0.0, value=float(audit.icms_base), step=1.0, key="bill_icms_base")
    c1, c2, c3, c4 = st.columns(4)
    audit.pis_value = c1.number_input("PIS (R$)", min_value=0.0, value=float(audit.pis_value), step=0.1, key="bill_pis")
    audit.cofins_value = c2.number_input("COFINS (R$)", min_value=0.0, value=float(audit.cofins_value), step=0.1, key="bill_cofins")
    audit.distribution_use_charge = c3.number_input("Uso da distribuição (R$)", min_value=0.0, value=float(audit.distribution_use_charge), step=1.0, key="bill_distribution")
    audit.gross_consumption_cost = c4.number_input("Custo bruto do consumo (R$)", min_value=0.0, value=float(audit.gross_consumption_cost), step=1.0, key="bill_gross_consumption")

audit = recalculate_audit(audit)

with st.container(horizontal=True):
    st.metric("Valor faturado", money(audit.invoice_amount), border=True)
    st.metric("Estimativa sem solar", money(audit.estimated_without_solar), border=True)
    st.metric("Economia no ciclo", money(audit.estimated_savings_month), border=True)
    st.metric("Projeção anual", money(audit.estimated_savings_year), border=True)
    st.metric("Projeção em 5 anos", money(audit.estimated_savings_5_years), border=True)

st.subheader("Balanço da unidade", icon=":material/energy_savings_leaf:")
with st.container(horizontal=True):
    st.metric("Consumida", f"{number_br(audit.consumption_kwh, 2)} kWh", border=True)
    st.metric(
        "Injetada medida",
        "Não informada" if audit.injected_measured_kwh is None else f"{number_br(audit.injected_measured_kwh, 2)} kWh",
        border=True,
    )
    st.metric("Compensada", f"{number_br(audit.compensated_kwh, 2)} kWh", border=True)
    st.metric("Saldo de créditos", f"{number_br(audit.credit_balance_kwh, 2)} kWh", border=True)

if audit.historical_consumption_kwh:
    st.subheader("Histórico de consumo", icon=":material/bar_chart:")
    history = pd.DataFrame(audit.historical_consumption_kwh, columns=["Mês", "Consumo (kWh)"])
    st.bar_chart(history, x="Mês", y="Consumo (kWh)", color="#2A6F97")
    st.caption(f"Média dos meses legíveis: {number_br(audit.historical_average_kwh, 2)} kWh/mês.")

st.subheader("Achados e recomendações", icon=":material/fact_check:")
findings = pd.DataFrame(audit.findings).rename(columns={
    "severity": "Prioridade",
    "title": "Achado",
    "evidence": "Evidência",
    "recommendation": "Recomendação",
})
st.dataframe(findings, hide_index=True)

with st.expander("Itens extraídos da fatura", icon=":material/table_view:"):
    item_frame = pd.DataFrame(items_as_rows(audit.items)).rename(columns={
        "description": "Descrição",
        "unit": "Unidade",
        "quantity": "Quantidade",
        "unit_price": "Tarifa unitária",
        "amount": "Valor",
        "icms": "ICMS do item",
    })
    st.dataframe(
        item_frame,
        hide_index=True,
        column_config={
            "Quantidade": st.column_config.NumberColumn(format="%.3f"),
            "Tarifa unitária": st.column_config.NumberColumn(format="R$ %.6f"),
            "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
            "ICMS do item": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )

for warning in audit.warnings:
    st.caption(f"- {warning}")

pdf = generate_bill_audit_pdf(audit)
filename = f"auditoria-fatura-{_slug(audit.unit_code)}-{_slug(audit.reference_month)}.pdf"
st.download_button(
    "Baixar relatório de auditoria em PDF",
    data=pdf,
    file_name=filename,
    mime="application/pdf",
    type="primary",
    icon=":material/picture_as_pdf:",
)

st.caption(
    "A análise automatizada é uma conferência técnica preliminar. Divergências que dependam de memória de massa, regras tarifárias específicas ou histórico completo devem ser validadas com a distribuidora."
)
