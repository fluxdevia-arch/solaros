from datetime import date, timedelta

import pandas as pd
import streamlit as st

from solar_crm.calculations import money
from solar_crm.db import query
from solar_crm.document_cache import service_contract_pdf
from solar_crm.ui import date_br, flash, page_intro, show_flash
from solar_crm.workflow import CONTRACT_STATUSES, create_service_contract, update_contract_status


CONTRACT_TEMPLATES = {
    "Pós-venda e monitoramento solar": {
        "title": "Contrato de gestão e pós-venda de energia solar",
        "scope": "Monitoramento periódico das usinas cadastradas, análise de geração e desempenho, conferência das informações de consumo e compensação, emissão de relatórios e comunicação de anomalias identificadas.",
        "contractor": "Acompanhar os dados conforme a periodicidade contratada, emitir relatórios, registrar ocorrências e orientar a contratante sobre ações corretivas. Visitas, peças e serviços fora do escopo dependem de aprovação.",
    },
    "Manutenção de sistema fotovoltaico": {
        "title": "Contrato de manutenção de sistema fotovoltaico",
        "scope": "Execução de manutenção preventiva e/ou corretiva no sistema fotovoltaico descrito nas ordens de serviço aprovadas, incluindo inspeções, medições, reapertos e relatório dos serviços realizados.",
        "contractor": "Executar os serviços com equipe qualificada, utilizar procedimentos de segurança aplicáveis, registrar evidências e comunicar a necessidade de materiais ou intervenções adicionais antes de executá-las.",
    },
    "Consultoria técnica": {
        "title": "Contrato de consultoria técnica em energia solar",
        "scope": "Prestação de consultoria técnica para diagnóstico, análise documental e energética, recomendações de adequação e entrega dos produtos técnicos definidos neste instrumento.",
        "contractor": "Realizar as análises com base nos documentos, medições e informações disponibilizados, apresentar conclusões e recomendações dentro do escopo e manter sigilo sobre as informações recebidas.",
    },
    "Projeto e dimensionamento": {
        "title": "Contrato de projeto e dimensionamento elétrico/fotovoltaico",
        "scope": "Elaboração dos estudos e documentos de projeto indicados neste instrumento, conforme dados de entrada fornecidos pela contratante e condições verificadas durante o levantamento.",
        "contractor": "Elaborar e entregar os documentos previstos no escopo. A execução da obra, fiscalização, aprovações de concessionária e alterações posteriores não estão incluídas salvo previsão expressa.",
    },
}

page_intro("Gere minutas padronizadas para pós-venda, manutenção, consultoria e projeto, com histórico e PDF.")
show_flash()

clients = query("SELECT id, name FROM clients WHERE status='Ativo' ORDER BY name")
contracts = query(
    """SELECT sc.*, c.name AS client_name FROM service_contracts sc
       JOIN clients c ON c.id=sc.client_id ORDER BY sc.created_at DESC"""
)

with st.container(horizontal=True):
    st.metric("Contratos gerados", len(contracts), border=True)
    st.metric("Rascunhos", sum(1 for row in contracts if row["status"] == "Rascunho"), border=True)
    st.metric("Enviados", sum(1 for row in contracts if row["status"] == "Enviado"), border=True)
    st.metric("Assinados", sum(1 for row in contracts if row["status"] == "Assinado"), border=True)

if not clients:
    st.warning("Cadastre um cliente antes de gerar contratos.", icon=":material/warning:")
else:
    with st.container(horizontal=True, horizontal_alignment="right"):
        new_contract = st.popover("Novo contrato", icon=":material/note_add:")

    with new_contract:
        contract_type = st.selectbox("Modelo", list(CONTRACT_TEMPLATES), key="contract_template")
        template = CONTRACT_TEMPLATES[contract_type]
        with st.form("new_service_contract", clear_on_submit=True):
            client_map = {row["name"]: row["id"] for row in clients}
            client_name = st.selectbox("Cliente", list(client_map))
            title = st.text_input("Título", value=template["title"])
            c1, c2 = st.columns(2)
            start_date = c1.date_input("Início", value=date.today())
            end_date = c2.date_input("Término previsto", value=date.today() + timedelta(days=365))
            c3, c4 = st.columns(2)
            duration = c3.number_input("Vigência (meses)", min_value=1, value=12, step=1)
            billing_cycle = c4.selectbox("Forma de cobrança", ["Mensal", "Por etapa", "Parcela única", "Anual"])
            amount = st.number_input("Valor contratado", min_value=0.0, step=100.0)
            payment_terms = st.text_area("Condições de pagamento", placeholder="Ex.: vencimento todo dia 10; reajuste anual pelo IPCA.")
            scope = st.text_area("Objeto e escopo", value=template["scope"], height=150)
            contractor_obligations = st.text_area("Obrigações da contratada", value=template["contractor"], height=130)
            client_obligations = st.text_area("Obrigações do cliente", value="Fornecer acesso, documentos e informações necessários; indicar responsável para acompanhamento; manter as instalações acessíveis e efetuar os pagamentos pactuados.")
            termination_terms = st.text_area("Rescisão e aviso prévio", value="Qualquer parte poderá solicitar o encerramento por escrito, com aviso prévio de 30 dias, preservando os valores vencidos e os serviços já executados.")
            additional_terms = st.text_area("Condições adicionais")
            venue = st.text_input("Cidade/foro", placeholder="Ex.: João Pessoa/PB")
            if st.form_submit_button("Gerar minuta", type="primary", icon=":material/save:"):
                try:
                    create_service_contract({
                        "client_id": client_map[client_name], "contract_type": contract_type,
                        "title": title, "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
                        "duration_months": duration, "amount": amount, "billing_cycle": billing_cycle,
                        "payment_terms": payment_terms, "scope": scope,
                        "contractor_obligations": contractor_obligations,
                        "client_obligations": client_obligations, "termination_terms": termination_terms,
                        "additional_terms": additional_terms, "venue": venue, "status": "Rascunho",
                    })
                    flash("Minuta contratual gerada.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

if contracts:
    st.subheader("Histórico de contratos", icon=":material/history:")
    frame = pd.DataFrame(contracts)[["number", "client_name", "contract_type", "start_date", "end_date", "amount", "billing_cycle", "status"]]
    frame.columns = ["Número", "Cliente", "Tipo", "Início", "Término", "Valor", "Cobrança", "Status"]
    frame["Início"] = frame["Início"].map(date_br)
    frame["Término"] = frame["Término"].map(date_br)
    st.dataframe(frame, hide_index=True, column_config={"Valor": st.column_config.NumberColumn(format="R$ %.2f"), "Cliente": st.column_config.TextColumn(pinned=True)})

    contract_map = {f"{row['number']} · {row['client_name']} · {row['contract_type']}": row for row in contracts}
    selected_label = st.selectbox("Selecionar contrato", list(contract_map), key="selected_contract")
    selected = contract_map[selected_label]
    with st.container(border=True):
        st.subheader(f"{selected['number']} · {selected['client_name']}", icon=":material/contract:")
        st.write(f"**{selected['title']}**")
        st.caption(f"{money(selected['amount'])} · cobrança {selected['billing_cycle'].lower()} · status {selected['status']}")
        st.download_button(
            "Baixar contrato em PDF",
            service_contract_pdf(selected["id"], str(selected.get("updated_at") or "")),
            file_name=f"{selected['number'].lower()}.pdf",
            mime="application/pdf",
            icon=":material/download:",
        )
    with st.expander("Atualizar situação do contrato", icon=":material/edit:"):
        new_status = st.segmented_control("Status", CONTRACT_STATUSES, default=selected["status"])
        if st.button("Salvar status", type="primary", icon=":material/save:"):
            update_contract_status(selected["id"], new_status)
            flash("Situação do contrato atualizada.")
            st.rerun()
else:
    st.info("Nenhum contrato de serviço gerado.", icon=":material/info:")

st.caption("As minutas são uma base administrativa. Revise o documento com assessoria jurídica antes da assinatura e adapte tributos, responsabilidades, garantias e foro ao serviço concreto.")
