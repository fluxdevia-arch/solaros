from datetime import date, timedelta

import pandas as pd
import streamlit as st

from solar_crm.calculations import money
from solar_crm.db import query
from solar_crm.document_cache import proposal_pdf
from solar_crm.records import PROPOSAL_STATUSES, create_proposal, update_proposal_status
from solar_crm.ui import date_br, flash, page_intro, show_flash


PROPOSAL_TEMPLATES = {
    "Consultoria técnica": {
        "title": "Proposta de consultoria técnica em energia solar",
        "scope": "Diagnóstico técnico e energético, análise dos documentos disponibilizados, reunião de levantamento e recomendações para melhoria, regularização ou tomada de decisão.",
        "deliverables": "Relatório técnico com diagnóstico e recomendações\nReunião de apresentação dos resultados\nPlano de ação priorizado",
        "exclusions": "Ensaios laboratoriais, taxas, ART/TRT, deslocamentos extraordinários, execução de obra, peças e serviços não descritos no escopo.",
    },
    "Projeto e dimensionamento FV": {
        "title": "Proposta de projeto e dimensionamento fotovoltaico",
        "scope": "Levantamento de premissas, dimensionamento de módulos, inversor, strings, cabos, proteções e croqui preliminar do arranjo fotovoltaico.",
        "deliverables": "Memorial de dimensionamento\nDiagrama e croqui de distribuição dos módulos por string\nLista técnica de cabos e proteções\nRevisão técnica do conjunto módulo/inversor",
        "exclusions": "Aprovação junto à distribuidora, projeto estrutural, SPDA, estudo de curto-circuito, execução, materiais e visitas adicionais, salvo contratação expressa.",
    },
    "Manutenção fotovoltaica": {
        "title": "Proposta de manutenção de sistema fotovoltaico",
        "scope": "Inspeção e manutenção preventiva ou corretiva do sistema fotovoltaico conforme levantamento e condições de acesso da instalação.",
        "deliverables": "Ordem de serviço\nInspeção visual e elétrica\nRegistro fotográfico\nRelatório dos serviços e recomendações",
        "exclusions": "Peças, equipamentos de elevação, adequações civis e elétricas não previstas, interrupções da distribuidora e serviços fora do escopo aprovado.",
    },
    "Pós-venda e monitoramento": {
        "title": "Proposta de gestão e pós-venda solar",
        "scope": "Monitoramento, conferência de geração e faturas, registro de ocorrências e emissão de relatórios periódicos das usinas e unidades beneficiárias contratadas.",
        "deliverables": "Monitoramento conforme plano contratado\nRelatório mensal de geração, consumo e economia\nGestão de alertas e ocorrências\nAcompanhamento das unidades beneficiárias",
        "exclusions": "Visitas, peças, limpeza, correções elétricas e serviços de terceiros não previstos no plano contratado.",
    },
}


page_intro("Crie, acompanhe e emita propostas comerciais profissionais para serviços, consultorias e projetos solares.")
show_flash()

with st.container(horizontal=True, vertical_alignment="center"):
    st.image("assets/ongrid_logo.png", width=300)
    st.caption("As propostas em PDF usam automaticamente a identidade visual da OnGrid Energia Solar e a assinatura técnica configurada no SolarOS.")

clients = query("SELECT id, name FROM clients WHERE status='Ativo' ORDER BY name")
opportunities = query(
    """SELECT id, lead_name, service_type, estimated_value FROM opportunities
       WHERE stage NOT IN ('Fechado perdido') ORDER BY updated_at DESC"""
)
proposals = query(
    """SELECT pr.*, c.name AS client_name, o.lead_name AS opportunity_name
       FROM proposals pr JOIN clients c ON c.id=pr.client_id
       LEFT JOIN opportunities o ON o.id=pr.opportunity_id
       ORDER BY pr.created_at DESC"""
)

with st.container(horizontal=True):
    st.metric("Propostas", len(proposals), border=True)
    st.metric("Em negociação", sum(1 for row in proposals if row["status"] in ("Emitida", "Enviada")), border=True)
    st.metric("Aprovadas", sum(1 for row in proposals if row["status"] == "Aprovada"), border=True)
    st.metric("Valor aprovado", money(sum(float(row["amount"] or 0) for row in proposals if row["status"] == "Aprovada")), border=True)

create_tab, history_tab = st.tabs([
    ":material/note_add: Nova proposta",
    ":material/history: Histórico e PDF",
])

with create_tab:
    if not clients:
        st.warning("Cadastre um cliente ativo antes de criar a proposta.", icon=":material/warning:")
    else:
        service_type = st.selectbox("Modelo de proposta", list(PROPOSAL_TEMPLATES), key="proposal_template")
        template = PROPOSAL_TEMPLATES[service_type]
        with st.form("new_proposal", clear_on_submit=True):
            client_map = {row["name"]: row["id"] for row in clients}
            client_name = st.selectbox("Cliente", list(client_map))
            opportunity_map = {"Sem vínculo com oportunidade": None}
            opportunity_map.update({
                f"{row['lead_name']} · {row['service_type']}": row["id"] for row in opportunities
            })
            opportunity_label = st.selectbox("Oportunidade do Kanban", list(opportunity_map))
            title = st.text_input("Título", value=template["title"])
            c1, c2, c3 = st.columns(3)
            issue_date = c1.date_input("Emissão", value=date.today())
            valid_until = c2.date_input("Validade", value=date.today() + timedelta(days=15))
            deadline_days = c3.number_input("Prazo de execução (dias)", min_value=1, value=15, step=1)
            amount = st.number_input("Investimento (R$)", min_value=0.0, value=0.0, step=100.0)
            payment_terms = st.text_area("Condições de pagamento", value="50% na aprovação e 50% na entrega, por PIX ou transferência bancária.")
            scope = st.text_area("Escopo", value=template["scope"], height=130)
            deliverables = st.text_area("Entregáveis — um item por linha", value=template["deliverables"], height=120)
            exclusions = st.text_area("Itens não inclusos", value=template["exclusions"], height=110)
            notes = st.text_area("Observações comerciais")
            submitted = st.form_submit_button("Salvar proposta", type="primary", icon=":material/save:")
        if submitted:
            try:
                create_proposal({
                    "client_id": client_map[client_name],
                    "opportunity_id": opportunity_map[opportunity_label],
                    "title": title,
                    "service_type": service_type,
                    "issue_date": issue_date.isoformat(),
                    "valid_until": valid_until.isoformat(),
                    "amount": amount,
                    "payment_terms": payment_terms,
                    "scope": scope,
                    "deliverables": deliverables,
                    "exclusions": exclusions,
                    "deadline_days": deadline_days,
                    "notes": notes,
                    "status": "Rascunho",
                })
                flash("Proposta criada com a identidade visual da OnGrid.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

with history_tab:
    if not proposals:
        st.info("Nenhuma proposta criada.", icon=":material/info:")
    else:
        frame = pd.DataFrame(proposals)[["number", "client_name", "service_type", "issue_date", "valid_until", "amount", "status"]]
        frame.columns = ["Número", "Cliente", "Serviço", "Emissão", "Validade", "Valor", "Status"]
        frame["Emissão"] = frame["Emissão"].map(date_br)
        frame["Validade"] = frame["Validade"].map(date_br)
        st.dataframe(
            frame,
            hide_index=True,
            column_config={
                "Cliente": st.column_config.TextColumn(pinned=True),
                "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )
        proposal_map = {
            f"{row['number']} · {row['client_name']} · {row['service_type']}": row
            for row in proposals
        }
        selected_label = st.selectbox("Selecionar proposta", list(proposal_map), key="selected_proposal")
        selected = proposal_map[selected_label]
        with st.container(border=True):
            st.subheader(f"{selected['number']} · {selected['client_name']}", icon=":material/request_quote:")
            st.write(f"**{selected['title']}**")
            st.caption(f"{money(selected['amount'])} · válida até {date_br(selected['valid_until'])} · {selected['status']}")
            st.download_button(
                "Baixar proposta OnGrid em PDF",
                proposal_pdf(selected["id"], str(selected.get("updated_at") or "")),
                file_name=f"{selected['number'].lower()}-ongrid.pdf",
                mime="application/pdf",
                type="primary",
                icon=":material/download:",
            )
        with st.expander("Atualizar situação", icon=":material/edit:"):
            new_status = st.segmented_control("Status", PROPOSAL_STATUSES, default=selected["status"])
            if st.button("Salvar status", type="primary", icon=":material/save:"):
                update_proposal_status(selected["id"], new_status)
                flash("Situação da proposta atualizada.")
                st.rerun()

st.caption("Revise valores, impostos, responsabilidades, prazos e exclusões antes do envio ao cliente.")
