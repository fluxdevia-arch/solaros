import re
import unicodedata
from datetime import date

import pandas as pd
import streamlit as st

from solar_crm.calculations import calculate_coverage, calculate_savings, money, number_br, percent
from solar_crm.db import available_months, query, query_df, query_one
from solar_crm.pdf_report import generate_client_report
from solar_crm.ui import client_options, month_label, page_intro

page_intro("Gere um demonstrativo PDF pronto para enviar ao cliente, com consumo, geração, economia, falhas e ações do período.")

clients = query("SELECT id, name FROM clients WHERE status='Ativo' ORDER BY name")
months = available_months()
if not clients or not months:
    st.warning("É necessário ter clientes, usinas e leituras cadastrados para emitir relatórios.", icon=":material/warning:")
    st.stop()

c_map = client_options(clients)
left, right = st.columns([1, 1])
client_name = left.selectbox("Cliente", list(c_map), key="report_client")
reference_month = right.selectbox("Mês de referência", months, format_func=month_label, key="report_month")
client_id = c_map[client_name]
settings = query_one("SELECT technical_name, technical_title, technical_registration, signature_image FROM settings WHERE id=1")

data = query_df(
    """SELECT p.name AS Usina, p.unit_code AS UC, p.expected_monthly_kwh AS Esperado,
              COALESCE(r.consumption_kwh,0) AS Consumo, COALESCE(r.generation_kwh,0) AS Geração,
              (SELECT COUNT(*) FROM beneficiaries b WHERE b.plant_id=p.id AND b.status='Ativo') AS Beneficiárias,
              COALESCE((SELECT SUM(br.allocated_kwh) FROM beneficiary_readings br
                        JOIN beneficiaries b ON b.id=br.beneficiary_id
                        WHERE b.plant_id=p.id AND br.reference_month=?),0) AS Beneficiada,
              COALESCE(r.availability_pct,0) AS Disponibilidade,
              COALESCE(r.billed_amount,0) AS Fatura,
              COALESCE(r.reference_amount,0) AS 'Custo sem solar',
              COALESCE(r.reference_amount-r.billed_amount,0) AS Economia,
              COALESCE(r.incidents,0) AS Ocorrências,
              COALESCE(r.failure_notes,'') AS Observações
       FROM plants p LEFT JOIN readings r ON r.plant_id=p.id AND r.reference_month=?
       WHERE p.client_id=? ORDER BY p.name""",
    (reference_month, reference_month, client_id),
)

if data.empty:
    st.info("Este cliente ainda não possui usinas.")
    st.stop()

missing_readings = int((data["Geração"] == 0).sum())
total_generation = float(data["Geração"].sum())
total_consumption = float(data["Consumo"].sum())
total_savings = float(data["Economia"].sum())
total_allocated = float(data["Beneficiada"].sum())
expected = float(data["Esperado"].sum())

with st.container(horizontal=True):
    st.metric("Usinas no relatório", len(data), border=True)
    st.metric("Geração consolidada", f"{number_br(total_generation / 1000, 2)} MWh", border=True)
    st.metric("Energia beneficiada", f"{number_br(total_allocated / 1000, 2)} MWh", border=True)
    st.metric("Cobertura do consumo", percent(calculate_coverage(total_generation, total_consumption)), border=True)
    st.metric("Economia estimada", money(total_savings), border=True)
    st.metric("Desempenho", percent(total_generation / expected * 100 if expected else 0), border=True)

if missing_readings:
    st.warning(f"{missing_readings} usina(s) sem geração registrada neste mês. O PDF será emitido com valores zerados para elas.", icon=":material/warning:")
else:
    st.success("Todos os dados necessários estão preenchidos para o período.", icon=":material/check_circle:")

preview, checklist = st.tabs([
    ":material/preview: Prévia dos dados",
    ":material/checklist: Checklist de envio",
])

with preview:
    st.dataframe(
        data,
        hide_index=True,
        column_config={
            "Usina": st.column_config.TextColumn(pinned=True),
            "Esperado": st.column_config.NumberColumn(format="%.0f kWh"),
            "Consumo": st.column_config.NumberColumn(format="%.0f kWh"),
            "Geração": st.column_config.NumberColumn(format="%.0f kWh"),
            "Beneficiada": st.column_config.NumberColumn(format="%.0f kWh"),
            "Disponibilidade": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
            "Fatura": st.column_config.NumberColumn(format="R$ %.2f"),
            "Custo sem solar": st.column_config.NumberColumn(format="R$ %.2f"),
            "Economia": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )

with checklist:
    st.checkbox("Leituras do portal de monitoramento conferidas", key="check_monitoring")
    st.checkbox("Faturas da distribuidora conferidas", key="check_bills")
    st.checkbox("Falhas e indisponibilidades descritas", key="check_failures")
    st.checkbox("Chamados e próximos passos atualizados", key="check_tickets")
    st.checkbox("Contato e e-mail do cliente validados", key="check_contact")
    st.caption("O checklist é operacional e não bloqueia a emissão do relatório.")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


with st.container(border=True):
    st.subheader("Emitir demonstrativo", icon=":material/picture_as_pdf:")
    st.caption("O PDF inclui resumo executivo, comparação esperado x realizado, detalhamento por usina, economia, falhas, ocorrências, agenda e assinatura profissional.")
    st.write(f"Assinatura: **{settings['technical_name']}** · {settings['technical_title']} · {settings['technical_registration']}")
    if settings["signature_image"]:
        st.success("Assinatura manuscrita configurada e pronta para este relatório.", icon=":material/draw:")
    else:
        st.info("Para inserir sua assinatura à mão acima da linha, envie a imagem em Configurações.", icon=":material/info:")
    if st.button("Gerar relatório PDF", type="primary", icon=":material/description:"):
        try:
            with st.spinner("Montando o demonstrativo..."):
                st.session_state["report_pdf"] = generate_client_report(client_id, reference_month)
                st.session_state["report_key"] = (client_id, reference_month)
            st.toast("Relatório gerado com sucesso.", icon=":material/check_circle:")
        except Exception as exc:
            st.error(f"Não foi possível gerar o relatório: {exc}")

    if st.session_state.get("report_pdf") and st.session_state.get("report_key") == (client_id, reference_month):
        filename = f"relatorio-{slugify(client_name)}-{reference_month[:7]}.pdf"
        st.download_button(
            "Baixar PDF",
            st.session_state["report_pdf"],
            filename,
            "application/pdf",
            type="primary",
            icon=":material/download:",
        )

st.caption("Privacidade: o PDF é gerado localmente. Revise os dados pessoais antes de compartilhar por e-mail ou mensageiro.")
