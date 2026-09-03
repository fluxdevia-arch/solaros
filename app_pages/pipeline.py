from datetime import date, timedelta

import streamlit as st

from solar_crm.calculations import money
from solar_crm.db import query, query_one
from solar_crm.ui import date_br, flash, page_intro, show_flash
from solar_crm.workflow import OPPORTUNITY_STAGES, create_opportunity, move_opportunity, set_opportunity_stage


page_intro("Acompanhe cada negociação desde o primeiro contato até o fechamento, com valor, probabilidade e próxima ação.")
show_flash()

clients = query("SELECT id, name, contact_name, phone, email FROM clients ORDER BY name")
opportunities = query("SELECT * FROM opportunities ORDER BY next_action_date, updated_at DESC")
active = [row for row in opportunities if row["stage"] not in {"Fechado ganho", "Fechado perdido"}]
pipeline_value = sum(float(row["estimated_value"] or 0) for row in active)
weighted_value = sum(float(row["estimated_value"] or 0) * float(row["probability_pct"] or 0) / 100 for row in active)
overdue = sum(1 for row in active if row.get("next_action_date") and row["next_action_date"] < date.today().isoformat())

with st.container(horizontal=True):
    st.metric("Negociações ativas", len(active), border=True)
    st.metric("Valor em negociação", money(pipeline_value), border=True)
    st.metric("Previsão ponderada", money(weighted_value), border=True)
    st.metric("Ações atrasadas", overdue, border=True)

with st.container(horizontal=True, horizontal_alignment="right"):
    new_opportunity = st.popover("Nova oportunidade", icon=":material/add:")
    update_stage = st.popover("Atualizar etapa", icon=":material/swap_horiz:")

with new_opportunity:
    client_choices = {"Novo contato / prospect": None, **{row["name"]: row for row in clients}}
    selected_client = st.selectbox("Vincular a cliente existente", list(client_choices), key="pipeline_client")
    client = client_choices[selected_client]
    with st.form("new_opportunity", clear_on_submit=True):
        lead_name = st.text_input("Nome da oportunidade", value=client["name"] if client else "")
        contact_name = st.text_input("Contato", value=client["contact_name"] if client else "")
        phone = st.text_input("Telefone", value=client["phone"] if client else "")
        email = st.text_input("E-mail", value=client["email"] if client else "")
        service_type = st.selectbox("Serviço", ["Pós-venda solar", "Manutenção", "Consultoria técnica", "Projeto/dimensionamento", "Laudo/inspeção", "Outro"])
        source = st.selectbox("Origem", ["Indicação", "Cliente da base", "WhatsApp", "Instagram", "Site", "Prospecção", "Outro"])
        c1, c2 = st.columns(2)
        estimated_value = c1.number_input("Valor estimado", min_value=0.0, step=100.0)
        probability = c2.number_input("Probabilidade (%)", min_value=0, max_value=100, value=20, step=5)
        c3, c4 = st.columns(2)
        expected_close = c3.date_input("Previsão de fechamento", value=date.today() + timedelta(days=30))
        next_action_date = c4.date_input("Data da próxima ação", value=date.today() + timedelta(days=2))
        next_action = st.text_input("Próxima ação", placeholder="Ex.: Fazer diagnóstico da conta de energia")
        owner = st.text_input("Responsável comercial")
        notes = st.text_area("Observações")
        if st.form_submit_button("Criar oportunidade", type="primary", icon=":material/save:"):
            try:
                create_opportunity({
                    "client_id": client["id"] if client else None,
                    "lead_name": lead_name, "contact_name": contact_name, "phone": phone,
                    "email": email, "service_type": service_type, "source": source,
                    "estimated_value": estimated_value, "probability_pct": probability,
                    "expected_close_date": expected_close.isoformat(), "next_action": next_action,
                    "next_action_date": next_action_date.isoformat(), "owner": owner, "notes": notes,
                })
                flash("Oportunidade adicionada ao Kanban.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

with update_stage:
    if opportunities:
        labels = {f"#{row['id']} · {row['lead_name']}": row for row in opportunities}
        selected = st.selectbox("Oportunidade", list(labels), key="pipeline_stage_item")
        selected_row = labels[selected]
        stage = st.selectbox("Nova etapa", OPPORTUNITY_STAGES, index=OPPORTUNITY_STAGES.index(selected_row["stage"]))
        lost_reason = st.text_area("Motivo da perda", disabled=stage != "Fechado perdido")
        if st.button("Atualizar etapa", type="primary", icon=":material/save:"):
            set_opportunity_stage(selected_row["id"], stage, lost_reason)
            flash("Etapa comercial atualizada.")
            st.rerun()
    else:
        st.caption("Cadastre uma oportunidade primeiro.")


def render_stage(stage: str, rows: list[dict]) -> None:
    st.subheader(stage)
    if not rows:
        st.caption("Nenhuma oportunidade nesta etapa.")
        return
    for item in rows:
        with st.container(border=True):
            st.markdown(f"**{item['lead_name']}**")
            st.caption(f"{item['service_type']} · {money(item['estimated_value'])}")
            if item.get("next_action"):
                action_date = date_br(item.get("next_action_date"))
                st.write(f":material/event: {action_date} · {item['next_action']}")
            st.caption(f"Responsável: {item.get('owner') or '-'} · Chance: {float(item['probability_pct'] or 0):.0f}%")
            with st.container(horizontal=True):
                current = OPPORTUNITY_STAGES.index(stage)
                if current > 0:
                    if st.button("Voltar", key=f"opp_back_{item['id']}", icon=":material/arrow_back:"):
                        move_opportunity(item["id"], -1)
                        st.rerun()
                if current < len(OPPORTUNITY_STAGES) - 1:
                    if st.button("Avançar", key=f"opp_next_{item['id']}", icon=":material/arrow_forward:"):
                        move_opportunity(item["id"], 1)
                        st.rerun()


st.subheader("Funil de negociações", icon=":material/view_kanban:")
st.caption("Use os botões nos cartões para mover rapidamente cada negociação.")
active_columns = st.columns(4)
for column, stage in zip(active_columns, OPPORTUNITY_STAGES[:4]):
    with column:
        render_stage(stage, [row for row in opportunities if row["stage"] == stage])

st.subheader("Resultados", icon=":material/flag:")
result_columns = st.columns(2)
for column, stage in zip(result_columns, OPPORTUNITY_STAGES[4:]):
    with column:
        render_stage(stage, [row for row in opportunities if row["stage"] == stage])
