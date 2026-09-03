from datetime import date, timedelta

import pandas as pd
import streamlit as st

from solar_crm.calculations import number_br, percent
from solar_crm.db import execute, query, query_df, query_one
from solar_crm.ui import client_options, date_br, flash, page_intro, plant_options, show_flash, status_badge

page_intro("Inventário técnico completo, histórico de desempenho e observações específicas de cada usina.")
show_flash()

clients = query("SELECT id, name FROM clients WHERE status='Ativo' ORDER BY name")
all_plants = query(
    """SELECT p.*, c.name AS client_name FROM plants p
       JOIN clients c ON c.id=p.client_id ORDER BY c.name, p.name"""
)

with st.container(horizontal=True, horizontal_alignment="right"):
    add_plant = st.popover("Nova usina", icon=":material/add:")
    plant_export = query_df("""SELECT c.name AS Cliente, p.name AS Usina, p.unit_code AS UC, p.distributor AS Distribuidora, p.installed_kwp AS Potencia_kWp, p.expected_monthly_kwh AS Geracao_esperada_kWh, p.status AS Status, p.next_cleaning_date AS Proxima_limpeza FROM plants p JOIN clients c ON c.id=p.client_id ORDER BY c.name, p.name""")
    st.download_button("Exportar", plant_export.to_csv(index=False).encode("utf-8-sig"), "usinas.csv", "text/csv", icon=":material/download:")

with add_plant:
    if not clients:
        st.warning("Cadastre um cliente antes de incluir uma usina.")
    else:
        c_map = client_options(clients)
        with st.form("new_plant", clear_on_submit=True):
            client_name = st.selectbox("Cliente", list(c_map))
            name = st.text_input("Nome da usina")
            uc = st.text_input("Número da unidade consumidora")
            distributor = st.text_input("Distribuidora")
            installed = st.number_input("Potência instalada (kWp)", min_value=0.0, step=0.1)
            expected = st.number_input("Geração esperada por mês (kWh)", min_value=0.0, step=100.0)
            commissioning = st.date_input("Data de comissionamento", value=date.today())
            inverter = st.text_input("Inversor(es)")
            modules = st.text_input("Módulos")
            next_cleaning = st.date_input("Próxima limpeza", value=date.today() + timedelta(days=90))
            notes = st.text_area("Observações operacionais")
            if st.form_submit_button("Cadastrar usina", type="primary", icon=":material/save:"):
                if not name.strip():
                    st.error("Informe o nome da usina.")
                else:
                    plant_id = execute(
                        """INSERT INTO plants (client_id, name, unit_code, distributor, installed_kwp, expected_monthly_kwh, commissioning_date, inverter, modules, status, next_cleaning_date, notes)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Operando', ?, ?)""",
                        (c_map[client_name], name.strip(), uc, distributor, installed, expected, commissioning.isoformat(), inverter, modules, next_cleaning.isoformat(), notes),
                    )
                    st.session_state.selected_plant_id = plant_id
                    flash("Usina cadastrada com sucesso.")
                    st.rerun()

if not all_plants:
    st.info("Nenhuma usina cadastrada.", icon=":material/info:")
    st.stop()

p_map = plant_options(all_plants)
selected_default = next((name for name, pid in p_map.items() if pid == st.session_state.get("selected_plant_id")), list(p_map)[0])
selected = st.selectbox("Usina", list(p_map), index=list(p_map).index(selected_default), key="plant_selector")
plant_id = p_map[selected]
st.session_state.selected_plant_id = plant_id
plant = query_one(
    """SELECT p.*, c.name AS client_name, c.contact_name, c.phone,
              mi.provider AS monitoring_provider, pi.last_sync_at AS monitoring_last_sync,
              pi.last_sync_status AS monitoring_sync_status
       FROM plants p JOIN clients c ON c.id=p.client_id
       LEFT JOIN plant_integrations pi ON pi.plant_id=p.id AND pi.status='Ativo'
       LEFT JOIN monitoring_integrations mi ON mi.id=pi.integration_id
       WHERE p.id=?""",
    (plant_id,),
)

latest = query_one("SELECT * FROM readings WHERE plant_id=? ORDER BY reference_month DESC LIMIT 1", (plant_id,))
generation = float(latest["generation_kwh"] or 0) if latest else 0
performance = generation / float(plant["expected_monthly_kwh"] or 1) * 100 if latest else 0
beneficiary_summary = query_one(
    """SELECT COUNT(*) AS count, COALESCE(SUM(allocation_pct),0) AS allocation
       FROM beneficiaries WHERE plant_id=? AND status='Ativo'""",
    (plant_id,),
)

with st.container(horizontal=True):
    st.metric("Potência instalada", f"{number_br(plant['installed_kwp'], 1)} kWp", border=True)
    st.metric("Geração esperada", f"{number_br(plant['expected_monthly_kwh'], 0)} kWh/mês", border=True)
    st.metric("Última geração", f"{number_br(generation, 0)} kWh", border=True)
    st.metric("Desempenho", percent(performance), border=True)
    st.metric("Beneficiárias ativas", beneficiary_summary["count"], border=True)
    st.metric("Integração", plant["monitoring_provider"] or "Não vinculada", border=True)

technical, beneficiaries_tab, history, notes_tab = st.tabs([
    ":material/memory: Ficha técnica",
    ":material/account_tree: Beneficiárias",
    ":material/query_stats: Histórico",
    ":material/sticky_note_2: Observações",
])

with technical:
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader(plant["name"])
            st.markdown(status_badge(plant["status"]))
            st.table({
                "Cliente": plant["client_name"],
                "Unidade consumidora": plant["unit_code"] or "-",
                "Distribuidora": plant["distributor"] or "-",
                "Tipo de ligação": plant["connection_type"] or "-",
                "Endereço": plant["address"] or "-",
                "Comissionamento": date_br(plant["commissioning_date"]),
            }, border="horizontal", width="stretch")
    with right:
        with st.container(border=True):
            st.subheader("Equipamentos", icon=":material/electrical_services:")
            st.table({
                "Inversor(es)": plant["inverter"] or "-",
                "Módulos": plant["modules"] or "-",
                "Garantia até": date_br(plant["warranty_expiry"]),
                "Próxima limpeza": date_br(plant["next_cleaning_date"]),
                "Portal de monitoramento": plant["monitoring_url"] or "-",
                "Integração por API": plant["monitoring_provider"] or "Não vinculada",
                "Última sincronização": date_br(plant["monitoring_last_sync"]),
            }, border="horizontal", width="stretch")

    cleaning_due = plant["next_cleaning_date"] and plant["next_cleaning_date"] < date.today().isoformat()
    if cleaning_due:
        st.warning("A limpeza desta usina está vencida. Crie ou atualize a atividade na agenda operacional.", icon=":material/cleaning_services:")

    with st.expander("Atualizar dados técnicos", icon=":material/edit:"):
        with st.form("edit_plant"):
            status = st.selectbox("Status", ["Operando", "Atenção", "Parada", "Desativada"], index=["Operando", "Atenção", "Parada", "Desativada"].index(plant["status"]) if plant["status"] in ["Operando", "Atenção", "Parada", "Desativada"] else 0)
            expected_edit = st.number_input("Geração esperada (kWh/mês)", min_value=0.0, value=float(plant["expected_monthly_kwh"] or 0), step=100.0)
            monitoring = st.text_input("Portal de monitoramento", value=plant["monitoring_url"] or "")
            next_cleaning_edit = st.date_input("Próxima limpeza", value=date.fromisoformat(plant["next_cleaning_date"]) if plant["next_cleaning_date"] else date.today() + timedelta(days=90))
            notes_edit = st.text_area("Observações", value=plant["notes"] or "")
            if st.form_submit_button("Salvar alterações", type="primary", icon=":material/save:"):
                execute("UPDATE plants SET status=?, expected_monthly_kwh=?, monitoring_url=?, next_cleaning_date=?, notes=? WHERE id=?", (status, expected_edit, monitoring, next_cleaning_edit.isoformat(), notes_edit, plant_id))
                flash("Usina atualizada.")
                st.rerun()

with beneficiaries_tab:
    beneficiaries = query(
        """SELECT * FROM beneficiaries WHERE plant_id=?
           ORDER BY CASE status WHEN 'Ativo' THEN 0 ELSE 1 END, name""",
        (plant_id,),
    )
    active_beneficiaries = [row for row in beneficiaries if row["status"] == "Ativo"]
    total_allocation = sum(float(row["allocation_pct"] or 0) for row in active_beneficiaries)

    st.subheader("Unidades consumidoras beneficiárias", icon=":material/account_tree:")
    st.caption("Cadastre todas as UCs que recebem créditos desta usina geradora. O rateio mensal será lançado na aba Leituras e faturas.")
    with st.container(horizontal=True):
        st.metric("Beneficiárias ativas", len(active_beneficiaries), border=True)
        st.metric("Percentual distribuído", percent(total_allocation), border=True)
        st.metric("Percentual disponível", percent(max(100 - total_allocation, 0)), border=True)

    if abs(total_allocation - 100) < 0.01:
        st.success("O rateio das unidades ativas fecha em 100%.", icon=":material/check_circle:")
    elif total_allocation < 100:
        st.warning(f"Ainda há {number_br(100 - total_allocation, 2)}% sem destinação no rateio.", icon=":material/warning:")
    else:
        st.error(f"O rateio ultrapassa 100% em {number_br(total_allocation - 100, 2)}%. Revise as unidades ativas.")

    with st.container(horizontal=True, horizontal_alignment="right"):
        add_beneficiary = st.popover("Nova beneficiária", icon=":material/add:")
        edit_beneficiary = st.popover("Editar beneficiária", icon=":material/edit:") if beneficiaries else None

    with add_beneficiary:
        with st.form("new_beneficiary", clear_on_submit=True):
            beneficiary_name = st.text_input("Nome da unidade beneficiária")
            beneficiary_uc = st.text_input("Número da unidade consumidora (UC)")
            beneficiary_holder = st.text_input("Titular da unidade")
            beneficiary_pct = st.number_input("Percentual de rateio (%)", min_value=0.0, max_value=100.0, step=0.1)
            beneficiary_notes = st.text_area("Observações")
            if st.form_submit_button("Cadastrar beneficiária", type="primary", icon=":material/save:"):
                duplicate = query_one(
                    "SELECT id FROM beneficiaries WHERE plant_id=? AND unit_code=?",
                    (plant_id, beneficiary_uc.strip()),
                )
                if not beneficiary_name.strip() or not beneficiary_uc.strip():
                    st.error("Informe o nome e o número da unidade consumidora.")
                elif duplicate:
                    st.error("Esta unidade consumidora já está cadastrada nesta usina.")
                elif total_allocation + beneficiary_pct > 100.001:
                    st.error("O percentual informado faz o rateio das unidades ativas ultrapassar 100%.")
                else:
                    execute(
                        """INSERT INTO beneficiaries
                           (plant_id, name, unit_code, holder_name, allocation_pct, status, notes)
                           VALUES (?, ?, ?, ?, ?, 'Ativo', ?)""",
                        (plant_id, beneficiary_name.strip(), beneficiary_uc.strip(), beneficiary_holder.strip(), beneficiary_pct, beneficiary_notes.strip()),
                    )
                    flash("Unidade beneficiária cadastrada.")
                    st.rerun()

    if edit_beneficiary is not None:
        with edit_beneficiary:
            beneficiary_map = {f"{row['name']} · {row['unit_code']}": row for row in beneficiaries}
            beneficiary_label = st.selectbox("Beneficiária", list(beneficiary_map), key="beneficiary_to_edit")
            beneficiary = beneficiary_map[beneficiary_label]
            with st.form("edit_beneficiary"):
                edit_name = st.text_input("Nome da unidade", value=beneficiary["name"])
                edit_uc = st.text_input("Número da UC", value=beneficiary["unit_code"])
                edit_holder = st.text_input("Titular", value=beneficiary["holder_name"] or "")
                edit_pct = st.number_input("Percentual de rateio (%)", min_value=0.0, max_value=100.0, value=float(beneficiary["allocation_pct"] or 0), step=0.1)
                edit_status = st.selectbox("Status", ["Ativo", "Inativo"], index=0 if beneficiary["status"] == "Ativo" else 1)
                edit_notes = st.text_area("Observações", value=beneficiary["notes"] or "")
                if st.form_submit_button("Salvar beneficiária", type="primary", icon=":material/save:"):
                    other_active_total = sum(
                        float(row["allocation_pct"] or 0)
                        for row in active_beneficiaries
                        if row["id"] != beneficiary["id"]
                    )
                    duplicate = query_one(
                        "SELECT id FROM beneficiaries WHERE plant_id=? AND unit_code=? AND id<>?",
                        (plant_id, edit_uc.strip(), beneficiary["id"]),
                    )
                    if not edit_name.strip() or not edit_uc.strip():
                        st.error("Informe o nome e o número da unidade consumidora.")
                    elif duplicate:
                        st.error("Esta unidade consumidora já está cadastrada nesta usina.")
                    elif edit_status == "Ativo" and other_active_total + edit_pct > 100.001:
                        st.error("O percentual informado faz o rateio das unidades ativas ultrapassar 100%.")
                    else:
                        execute(
                            """UPDATE beneficiaries SET name=?, unit_code=?, holder_name=?,
                               allocation_pct=?, status=?, notes=? WHERE id=?""",
                            (edit_name.strip(), edit_uc.strip(), edit_holder.strip(), edit_pct, edit_status, edit_notes.strip(), beneficiary["id"]),
                        )
                        flash("Unidade beneficiária atualizada.")
                        st.rerun()

    if beneficiaries:
        beneficiary_df = pd.DataFrame(beneficiaries).rename(columns={
            "name": "Beneficiária",
            "unit_code": "UC",
            "holder_name": "Titular",
            "allocation_pct": "Rateio",
            "status": "Status",
            "notes": "Observações",
        })[["Beneficiária", "UC", "Titular", "Rateio", "Status", "Observações"]]
        st.dataframe(
            beneficiary_df,
            hide_index=True,
            column_config={
                "Beneficiária": st.column_config.TextColumn(pinned=True),
                "Rateio": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
    else:
        st.info("Nenhuma unidade beneficiária cadastrada nesta usina.", icon=":material/info:")

with history:
    readings = query_df(
        """SELECT reference_month AS Mês, generation_kwh AS Geração, consumption_kwh AS Consumo,
                  availability_pct AS Disponibilidade, performance_ratio AS 'Índice de performance',
                  downtime_hours AS 'Indisponibilidade (h)', incidents AS Ocorrências
           FROM readings WHERE plant_id=? ORDER BY reference_month""",
        (plant_id,),
    )
    if not readings.empty:
        readings["Mês"] = pd.to_datetime(readings["Mês"])
        st.line_chart(readings, x="Mês", y=["Geração", "Consumo"], x_label="Mês", y_label="Energia (kWh)")
        st.dataframe(
            readings.sort_values("Mês", ascending=False),
            hide_index=True,
            column_config={
                "Mês": st.column_config.DateColumn(format="MMM/YYYY"),
                "Geração": st.column_config.NumberColumn(format="%.0f kWh"),
                "Consumo": st.column_config.NumberColumn(format="%.0f kWh"),
                "Disponibilidade": st.column_config.NumberColumn(format="%.1f%%"),
                "Índice de performance": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
    else:
        st.caption("Sem leituras registradas para esta usina.")

with notes_tab:
    st.subheader("Orientações permanentes", icon=":material/info:")
    st.write(plant["notes"] or "Nenhuma observação operacional cadastrada.")
    st.subheader("Ocorrências registradas", icon=":material/report_problem:")
    tickets = query_df(
        """SELECT opened_at AS Abertura, title AS Ocorrência, category AS Categoria,
                  severity AS Severidade, status AS Status, root_cause AS Causa, resolution AS Solução
           FROM tickets WHERE plant_id=? ORDER BY opened_at DESC""",
        (plant_id,),
    )
    if tickets.empty:
        st.success("Nenhuma ocorrência registrada.", icon=":material/check_circle:")
    else:
        tickets["Abertura"] = tickets["Abertura"].map(date_br)
        st.dataframe(tickets, hide_index=True)
