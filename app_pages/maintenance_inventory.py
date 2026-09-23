from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from solar_crm.db import query
from solar_crm.maintenance import (
    MOVEMENT_TYPES,
    create_maintenance_plan,
    create_stock_item,
    generate_due_maintenance_orders,
    maintenance_plans,
    record_stock_movement,
    stock_items,
    stock_movements,
    update_maintenance_plan,
    update_maintenance_plan_status,
    update_stock_item,
)
from solar_crm.ui import date_br, flash, money, page_intro, render_delete_control, show_flash


page_intro("Programe manutenções recorrentes, gere ordens de serviço automaticamente e controle peças usadas em campo.")
show_flash()

generated_orders = generate_due_maintenance_orders(horizon_days=0)
if generated_orders:
    st.success(f"{len(generated_orders)} ordem(ns) preventiva(s) gerada(s) para os próximos 45 dias.", icon=":material/event_available:")

plans = maintenance_plans()
items = stock_items(active_only=False)
movements = stock_movements()

with st.container(horizontal=True):
    st.metric("Planos ativos", sum(int(row["active"]) for row in plans), border=True)
    st.metric("Preventivas em 45 dias", sum(
        int(row["active"]) and str(row["next_due_date"])[:10] <= (date.today() + timedelta(days=45)).isoformat()
        for row in plans
    ), border=True)
    st.metric("Itens em estoque", sum(1 for row in items if row["active"]), border=True)
    st.metric("Estoque baixo", sum(float(row["balance"]) <= float(row["minimum_quantity"]) for row in items if row["active"]), border=True)

agenda_tab, stock_tab, movements_tab = st.tabs([
    ":material/event_repeat: Agenda preventiva",
    ":material/inventory_2: Estoque",
    ":material/swap_vert: Movimentações",
])

with agenda_tab:
    clients = query("SELECT id, name, contact_name, phone FROM clients WHERE status='Ativo' ORDER BY name")
    plants = query("SELECT id, client_id, name, unit_code, address FROM plants WHERE status!='Desativada' ORDER BY name")
    contracts = query("SELECT id, client_id, plan, billing_cycle FROM contracts WHERE status='Ativo' ORDER BY id DESC")
    templates = query("SELECT id, name FROM inspection_checklist_templates WHERE active=1 ORDER BY name")

    with st.container(horizontal=True, horizontal_alignment="right"):
        add_plan = st.popover("Novo plano preventivo", icon=":material/add_task:")
        if st.button("Gerar agenda agora", icon=":material/autorenew:"):
            created = generate_due_maintenance_orders(horizon_days=90)
            flash(f"Agenda atualizada. {len(created)} nova(s) O.S. gerada(s).")
            st.rerun()

    with add_plan:
        if not clients or not plants:
            st.warning("Cadastre cliente e usina antes de criar um plano.")
        else:
            client_map = {row["name"]: row for row in clients}
            client_name = st.selectbox("Cliente", list(client_map), key="preventive_client")
            client = client_map[client_name]
            client_plants = [row for row in plants if row["client_id"] == client["id"]]
            if not client_plants:
                st.warning("Este cliente não possui usina ativa.")
            else:
                plant_map = {f"{row['name']} · {row['unit_code'] or '-'}": row for row in client_plants}
                plant_label = st.selectbox("Usina", list(plant_map), key="preventive_plant")
                plant = plant_map[plant_label]
                contract_map = {"Sem contrato vinculado": None, **{
                    f"#{row['id']} · {row['plan']}": row["id"] for row in contracts if row["client_id"] == client["id"]
                }}
                template_map = {"Sem modelo de vistoria": None, **{row["name"]: row["id"] for row in templates}}
                with st.form("new_maintenance_plan", clear_on_submit=True):
                    name = st.text_input("Nome do plano", value="Manutenção preventiva periódica")
                    frequency = st.selectbox("Periodicidade", [1, 2, 3, 4, 6, 12, 18, 24], index=4, format_func=lambda value: f"A cada {value} mês(es)")
                    next_due = st.date_input("Próxima manutenção", value=date.today() + timedelta(days=30))
                    lead_days = st.number_input("Antecedência para gerar a O.S. (dias)", min_value=0, max_value=180, value=30)
                    contract_label = st.selectbox("Contrato", list(contract_map))
                    template_label = st.selectbox("Checklist da vistoria", list(template_map))
                    priority = st.selectbox("Prioridade", ["Baixa", "Média", "Alta", "Crítica"], index=1)
                    assignee = st.text_input("Equipe / responsável")
                    work_description = st.text_area(
                        "Escopo da preventiva",
                        value="Executar checklist preventivo, medições elétricas, inspeção termográfica quando aplicável, limpeza técnica e registro fotográfico.",
                        height=110,
                    )
                    safety = st.text_area("Instruções de segurança", value="Aplicar APR, bloqueio, etiquetagem e procedimentos de trabalho em altura quando aplicáveis.", height=90)
                    if st.form_submit_button("Criar plano e programar", type="primary", icon=":material/save:", width="stretch"):
                        try:
                            create_maintenance_plan({
                                "client_id": client["id"], "plant_id": plant["id"],
                                "contract_id": contract_map[contract_label],
                                "checklist_template_id": template_map[template_label],
                                "name": name, "frequency_months": frequency,
                                "next_due_date": next_due.isoformat(), "lead_days": lead_days,
                                "priority": priority, "assignee": assignee,
                                "work_description": work_description, "safety_instructions": safety,
                            })
                            flash("Plano preventivo criado. A agenda será gerada automaticamente.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))

    if plans:
        plan_frame = pd.DataFrame(plans)[[
            "id", "next_due_date", "name", "client_name", "plant_name", "frequency_months",
            "priority", "assignee", "contract_name", "checklist_name", "generated_count", "active",
        ]]
        plan_frame.columns = ["ID", "Próxima", "Plano", "Cliente", "Usina", "Meses", "Prioridade", "Responsável", "Contrato", "Checklist", "O.S. geradas", "Ativo"]
        plan_frame["Próxima"] = plan_frame["Próxima"].map(date_br)
        st.dataframe(plan_frame, hide_index=True, width="stretch", column_config={"Plano": st.column_config.TextColumn(pinned=True), "Ativo": st.column_config.CheckboxColumn()})

        plan_map = {f"#{row['id']} · {row['client_name']} · {row['plant_name']} · {row['name']}": row for row in plans}
        selected_plan_label = st.selectbox("Administrar plano", list(plan_map), key="maintenance_plan_admin")
        selected_plan = plan_map[selected_plan_label]
        with st.expander("Editar programação", icon=":material/edit_calendar:"):
            with st.form(f"edit_maintenance_plan_{selected_plan['id']}"):
                edit_frequency = st.selectbox(
                    "Periodicidade (meses)", [1, 2, 3, 4, 6, 12, 18, 24],
                    index=[1, 2, 3, 4, 6, 12, 18, 24].index(int(selected_plan["frequency_months"])) if int(selected_plan["frequency_months"]) in [1, 2, 3, 4, 6, 12, 18, 24] else 4,
                )
                edit_due = st.date_input("Próxima manutenção", value=date.fromisoformat(str(selected_plan["next_due_date"])[:10]))
                edit_lead = st.number_input("Antecedência (dias)", min_value=0, max_value=180, value=int(selected_plan["lead_days"] or 0))
                edit_priority = st.selectbox("Prioridade", ["Baixa", "Média", "Alta", "Crítica"], index=["Baixa", "Média", "Alta", "Crítica"].index(selected_plan["priority"]))
                edit_assignee = st.text_input("Equipe / responsável", value=selected_plan.get("assignee") or "")
                edit_scope = st.text_area("Escopo", value=selected_plan["work_description"], height=100)
                edit_safety = st.text_area("Segurança", value=selected_plan.get("safety_instructions") or "", height=80)
                if st.form_submit_button("Salvar programação", type="primary", icon=":material/save:"):
                    try:
                        update_maintenance_plan(selected_plan["id"], {
                            "frequency_months": edit_frequency, "next_due_date": edit_due.isoformat(),
                            "lead_days": edit_lead, "priority": edit_priority, "assignee": edit_assignee,
                            "work_description": edit_scope, "safety_instructions": edit_safety,
                        })
                        flash("Programação preventiva atualizada.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        with st.container(horizontal=True):
            target_active = not bool(selected_plan["active"])
            if st.button("Reativar plano" if target_active else "Pausar plano", icon=":material/pause_circle:" if not target_active else ":material/play_circle:"):
                update_maintenance_plan_status(selected_plan["id"], target_active)
                flash("Plano atualizado.")
                st.rerun()
        render_delete_control("maintenance_plan", selected_plan["id"], f"plano {selected_plan['name']}")
    else:
        st.info("Nenhum plano preventivo cadastrado.", icon=":material/info:")

with stock_tab:
    with st.container(horizontal=True, horizontal_alignment="right"):
        add_item = st.popover("Novo item", icon=":material/add_box:")
    with add_item:
        with st.form("new_stock_item", clear_on_submit=True):
            sku = st.text_input("Código / SKU")
            name = st.text_input("Item", placeholder="Ex.: DPS CC 1000 V tipo 2")
            category = st.selectbox("Categoria", ["Proteções", "Cabos", "Conectores", "Inversores", "Módulos", "Estruturas", "Ferramentas", "Consumíveis", "Outros"])
            unit = st.selectbox("Unidade", ["un", "m", "kit", "rolo", "caixa", "par"])
            minimum = st.number_input("Estoque mínimo", min_value=0.0, value=1.0, step=1.0)
            location = st.text_input("Localização", placeholder="Ex.: Prateleira A2")
            initial = st.number_input("Saldo inicial", min_value=0.0, value=0.0, step=1.0)
            cost = st.number_input("Custo unitário inicial (R$)", min_value=0.0, value=0.0, step=1.0)
            if st.form_submit_button("Cadastrar item", type="primary", icon=":material/save:", width="stretch"):
                try:
                    create_stock_item({
                        "sku": sku, "name": name, "category": category, "unit": unit,
                        "minimum_quantity": minimum, "location": location,
                        "initial_quantity": initial, "unit_cost": cost,
                    })
                    flash("Item cadastrado no estoque.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    active_items = [row for row in items if row["active"]]
    if active_items:
        stock_frame = pd.DataFrame(active_items)[["sku", "name", "category", "unit", "balance", "minimum_quantity", "location"]]
        stock_frame.columns = ["SKU", "Item", "Categoria", "Unidade", "Saldo", "Mínimo", "Localização"]
        st.dataframe(
            stock_frame,
            hide_index=True,
            width="stretch",
            column_config={"Item": st.column_config.TextColumn(pinned=True), "Saldo": st.column_config.NumberColumn(format="%.2f"), "Mínimo": st.column_config.NumberColumn(format="%.2f")},
        )
        low = [row for row in active_items if float(row["balance"]) <= float(row["minimum_quantity"])]
        if low:
            st.warning("Reposição necessária: " + ", ".join(f"{row['name']} ({float(row['balance']):g} {row['unit']})" for row in low), icon=":material/warning:")
        item_map = {f"{row['name']} · saldo {float(row['balance']):g} {row['unit']}": row for row in active_items}
        selected_item_label = st.selectbox("Administrar item", list(item_map), key="stock_item_admin")
        selected_item = item_map[selected_item_label]
        with st.expander("Editar item", icon=":material/edit:"):
            categories = ["Proteções", "Cabos", "Conectores", "Inversores", "Módulos", "Estruturas", "Ferramentas", "Consumíveis", "Outros"]
            units = ["un", "m", "kit", "rolo", "caixa", "par"]
            with st.form(f"edit_stock_item_{selected_item['id']}"):
                edit_sku = st.text_input("Código / SKU", value=selected_item.get("sku") or "")
                edit_name = st.text_input("Item", value=selected_item["name"])
                edit_category = st.selectbox("Categoria", categories, index=categories.index(selected_item["category"]) if selected_item["category"] in categories else len(categories) - 1)
                edit_unit = st.selectbox("Unidade", units, index=units.index(selected_item["unit"]) if selected_item["unit"] in units else 0)
                edit_minimum = st.number_input("Estoque mínimo", min_value=0.0, value=float(selected_item["minimum_quantity"]), step=1.0)
                edit_location = st.text_input("Localização", value=selected_item.get("location") or "")
                edit_active = st.toggle("Item ativo", value=bool(selected_item["active"]))
                if st.form_submit_button("Salvar item", type="primary", icon=":material/save:"):
                    try:
                        update_stock_item(selected_item["id"], {
                            "sku": edit_sku, "name": edit_name, "category": edit_category,
                            "unit": edit_unit, "minimum_quantity": edit_minimum,
                            "location": edit_location, "active": edit_active,
                        })
                        flash("Item atualizado.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        render_delete_control("stock_item", selected_item["id"], f"item {selected_item['name']}")
    else:
        st.info("Nenhum item cadastrado no estoque.", icon=":material/info:")

with movements_tab:
    active_items = [row for row in items if row["active"]]
    orders = query("SELECT id, number, title FROM service_orders WHERE status NOT IN ('Cancelada') ORDER BY id DESC LIMIT 250")
    if not active_items:
        st.info("Cadastre um item antes de movimentar o estoque.")
    else:
        item_map = {f"{row['name']} · {float(row['balance']):g} {row['unit']}": row for row in active_items}
        order_map = {"Sem O.S. vinculada": None, **{f"{row['number']} · {row['title']}": row["id"] for row in orders}}
        with st.form("stock_movement", clear_on_submit=True):
            item_label = st.selectbox("Item", list(item_map))
            movement_type = st.segmented_control("Movimentação", MOVEMENT_TYPES, default="Saída")
            quantity = st.number_input("Quantidade", min_value=0.01, value=1.0, step=1.0)
            unit_cost = st.number_input("Custo unitário (R$)", min_value=0.0, value=0.0, step=1.0)
            order_label = st.selectbox("Ordem de serviço", list(order_map))
            notes = st.text_area("Observação")
            if st.form_submit_button("Registrar movimentação", type="primary", icon=":material/swap_vert:", width="stretch"):
                try:
                    item = item_map[item_label]
                    record_stock_movement(item["id"], movement_type, quantity, unit_cost, order_map[order_label], notes=notes)
                    flash("Movimentação registrada.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    if movements:
        movement_frame = pd.DataFrame(movements)[["moved_at", "movement_type", "item_name", "quantity", "unit", "unit_cost", "service_order_number", "notes"]]
        movement_frame.columns = ["Data", "Tipo", "Item", "Quantidade", "Unidade", "Custo unitário", "O.S.", "Observação"]
        movement_frame["Data"] = movement_frame["Data"].map(date_br)
        st.dataframe(movement_frame, hide_index=True, width="stretch", column_config={"Item": st.column_config.TextColumn(pinned=True), "Custo unitário": st.column_config.NumberColumn(format="R$ %.2f")})
        total_entries = sum(float(row["quantity"]) * float(row["unit_cost"]) for row in movements if row["movement_type"] in {"Entrada", "Ajuste positivo"})
        st.caption(f"Valor histórico das entradas exibidas: {money(total_entries)}")
        movement_map = {
            f"#{row['id']} · {date_br(row['moved_at'])} · {row['movement_type']} · {row['item_name']}": row
            for row in movements
        }
        movement_label = st.selectbox("Administrar movimentação", list(movement_map), key="stock_movement_admin")
        render_delete_control("stock_movement", movement_map[movement_label]["id"], movement_label)
