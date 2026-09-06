from datetime import date, timedelta

import pandas as pd
import streamlit as st

from solar_crm.calculations import number_br, percent
from solar_crm.db import execute, query, query_df, query_one
from solar_crm.plant_equipment import (
    EQUIPMENT_STATUSES,
    EQUIPMENT_TYPES,
    MAX_PHOTOS_PER_EQUIPMENT,
    POWER_UNITS,
    add_equipment_photo,
    create_equipment,
    ensure_equipment_inventory_schema,
    equipment_for_plant,
    equipment_photos,
    update_equipment,
)
from solar_crm.ui import client_options, date_br, flash, page_intro, plant_options, render_delete_control, show_flash, status_badge

page_intro("Inventário técnico completo, histórico de desempenho e observações específicas de cada usina.")
show_flash()
ensure_equipment_inventory_schema()

clients = query("SELECT id, name FROM clients WHERE status='Ativo' ORDER BY name")
all_plants = query(
    """SELECT p.*, c.name AS client_name FROM plants p
       JOIN clients c ON c.id=p.client_id ORDER BY c.name, p.name"""
)

with st.container(horizontal=True, horizontal_alignment="right"):
    add_plant = st.popover("Nova usina", icon=":material/add:")
    plant_export = query_df("""SELECT c.name AS "Cliente", p.name AS "Usina", p.unit_code AS "UC", p.distributor AS "Distribuidora", p.installed_kwp AS "Potencia_kWp", p.expected_monthly_kwh AS "Geracao_esperada_kWh", p.status AS "Status", p.next_cleaning_date AS "Proxima_limpeza" FROM plants p JOIN clients c ON c.id=p.client_id ORDER BY c.name, p.name""")
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

technical, equipment_tab, beneficiaries_tab, history, notes_tab = st.tabs([
    ":material/memory: Ficha técnica",
    ":material/solar_power: Equipamentos",
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

    render_delete_control(
        "plant",
        plant_id,
        f"usina {plant['name']}",
        state_keys=("selected_plant_id", "report_pdf", "report_key"),
        extra_warning="As leituras e beneficiárias desta usina deixarão de compor os relatórios.",
    )

with equipment_tab:
    equipment_rows = equipment_for_plant(plant_id)
    inverter_count = sum(int(row["quantity"] or 0) for row in equipment_rows if row["equipment_type"] == "Inversor")
    panel_count = sum(int(row["quantity"] or 0) for row in equipment_rows if row["equipment_type"] == "Painel solar")
    photo_count = sum(int(row["photo_count"] or 0) for row in equipment_rows)

    with st.container(horizontal=True):
        st.metric("Inversores", inverter_count, border=True)
        st.metric("Painéis solares", panel_count, border=True)
        st.metric("Fotos cadastradas", photo_count, border=True)

    with st.container(horizontal=True, horizontal_alignment="right"):
        add_equipment = st.popover("Cadastrar equipamento", icon=":material/add:")

    with add_equipment:
        with st.form("new_plant_equipment", clear_on_submit=True):
            new_type = st.selectbox("Tipo", EQUIPMENT_TYPES, key="new_equipment_type")
            new_manufacturer = st.text_input("Fabricante")
            new_model = st.text_input("Modelo")
            new_quantity = st.number_input("Quantidade", min_value=1, value=1, step=1)
            new_serials = st.text_area(
                "Números de série",
                help="Informe um número por linha. Também é possível separar por vírgula.",
            )
            new_power = st.number_input("Potência nominal", min_value=0.0, step=0.1)
            new_power_unit = st.selectbox("Unidade da potência", POWER_UNITS)
            new_installation = st.date_input("Data de instalação", value=None)
            new_warranty = st.date_input("Garantia até", value=None)
            new_location = st.text_input("Localização na usina", placeholder="Ex.: parede norte, cobertura bloco A")
            new_status = st.selectbox("Status", EQUIPMENT_STATUSES)
            new_notes = st.text_area("Dados técnicos e observações")
            new_photos = st.file_uploader(
                "Fotos do equipamento",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                max_upload_size=12,
            ) or []
            if st.form_submit_button("Salvar equipamento", type="primary", icon=":material/save:"):
                if len(new_photos) > MAX_PHOTOS_PER_EQUIPMENT:
                    st.error(f"Envie no máximo {MAX_PHOTOS_PER_EQUIPMENT} fotos por equipamento.")
                else:
                    try:
                        equipment_id = create_equipment(plant_id, {
                            "equipment_type": new_type,
                            "manufacturer": new_manufacturer,
                            "model": new_model,
                            "quantity": new_quantity,
                            "serial_numbers": new_serials,
                            "nominal_power": new_power,
                            "power_unit": new_power_unit,
                            "installation_date": new_installation.isoformat() if new_installation else None,
                            "warranty_expiry": new_warranty.isoformat() if new_warranty else None,
                            "location": new_location,
                            "status": new_status,
                            "notes": new_notes,
                        })
                        for uploaded in new_photos:
                            add_equipment_photo(equipment_id, uploaded.getvalue(), uploaded.name, uploaded.name)
                        flash("Equipamento e fotos cadastrados com sucesso.")
                        st.rerun()
                    except (ValueError, OSError) as exc:
                        st.error(str(exc))

    if not equipment_rows:
        st.info("Nenhum inversor ou painel cadastrado nesta usina.", icon=":material/info:")
    else:
        equipment_df = pd.DataFrame(equipment_rows).rename(columns={
            "equipment_type": "Tipo", "manufacturer": "Fabricante", "model": "Modelo",
            "quantity": "Quantidade", "serial_numbers": "Números de série",
            "nominal_power": "Potência", "power_unit": "Unidade", "status": "Status",
            "photo_count": "Fotos",
        })
        st.dataframe(
            equipment_df[["Tipo", "Fabricante", "Modelo", "Quantidade", "Números de série", "Potência", "Unidade", "Status", "Fotos"]],
            hide_index=True,
            column_config={
                "Tipo": st.column_config.TextColumn(pinned=True),
                "Quantidade": st.column_config.NumberColumn(format="%d"),
                "Potência": st.column_config.NumberColumn(format="%.2f"),
            },
        )

        equipment_map = {
            f"#{row['id']} · {row['equipment_type']} · {row['manufacturer'] or 'Sem fabricante'} {row['model'] or ''}": row
            for row in equipment_rows
        }
        equipment_label = st.selectbox("Equipamento para consultar ou editar", list(equipment_map), key="plant_equipment_selector")
        selected_equipment = equipment_map[equipment_label]

        with st.container(border=True):
            st.subheader(
                f"{selected_equipment['equipment_type']} · {selected_equipment['manufacturer'] or 'Fabricante não informado'}",
                icon=":material/memory:",
            )
            st.table({
                "Modelo": selected_equipment["model"] or "-",
                "Quantidade": str(selected_equipment["quantity"]),
                "Potência nominal": f"{number_br(selected_equipment['nominal_power'], 2)} {selected_equipment['power_unit']}",
                "Números de série": (selected_equipment["serial_numbers"] or "-").replace("\n", " · "),
                "Instalação": date_br(selected_equipment["installation_date"]),
                "Garantia até": date_br(selected_equipment["warranty_expiry"]),
                "Localização": selected_equipment["location"] or "-",
                "Status": selected_equipment["status"],
                "Observações": selected_equipment["notes"] or "-",
            }, border="horizontal", width="stretch")

        with st.expander("Editar equipamento", icon=":material/edit:"):
            with st.form(f"edit_plant_equipment_{selected_equipment['id']}"):
                edit_key = f"equipment_edit_{selected_equipment['id']}"
                edit_type = st.selectbox("Tipo", EQUIPMENT_TYPES, index=EQUIPMENT_TYPES.index(selected_equipment["equipment_type"]), key=f"{edit_key}_type")
                edit_manufacturer = st.text_input("Fabricante", value=selected_equipment["manufacturer"] or "", key=f"{edit_key}_manufacturer")
                edit_model = st.text_input("Modelo", value=selected_equipment["model"] or "", key=f"{edit_key}_model")
                edit_quantity = st.number_input("Quantidade", min_value=1, value=int(selected_equipment["quantity"]), step=1, key=f"{edit_key}_quantity")
                edit_serials = st.text_area("Números de série", value=selected_equipment["serial_numbers"] or "", key=f"{edit_key}_serials")
                edit_power = st.number_input("Potência nominal", min_value=0.0, value=float(selected_equipment["nominal_power"] or 0), step=0.1, key=f"{edit_key}_power")
                edit_unit = st.selectbox("Unidade da potência", POWER_UNITS, index=POWER_UNITS.index(selected_equipment["power_unit"]) if selected_equipment["power_unit"] in POWER_UNITS else 0, key=f"{edit_key}_unit")
                edit_installation = st.date_input("Data de instalação", value=date.fromisoformat(selected_equipment["installation_date"]) if selected_equipment["installation_date"] else None, key=f"{edit_key}_installation")
                edit_warranty = st.date_input("Garantia até", value=date.fromisoformat(selected_equipment["warranty_expiry"]) if selected_equipment["warranty_expiry"] else None, key=f"{edit_key}_warranty")
                edit_location = st.text_input("Localização", value=selected_equipment["location"] or "", key=f"{edit_key}_location")
                edit_status = st.selectbox("Status", EQUIPMENT_STATUSES, index=EQUIPMENT_STATUSES.index(selected_equipment["status"]) if selected_equipment["status"] in EQUIPMENT_STATUSES else 0, key=f"{edit_key}_status")
                edit_notes = st.text_area("Dados técnicos e observações", value=selected_equipment["notes"] or "", key=f"{edit_key}_notes")
                if st.form_submit_button("Atualizar equipamento", type="primary", icon=":material/save:"):
                    update_equipment(selected_equipment["id"], {
                        "equipment_type": edit_type, "manufacturer": edit_manufacturer,
                        "model": edit_model, "quantity": edit_quantity,
                        "serial_numbers": edit_serials, "nominal_power": edit_power,
                        "power_unit": edit_unit,
                        "installation_date": edit_installation.isoformat() if edit_installation else None,
                        "warranty_expiry": edit_warranty.isoformat() if edit_warranty else None,
                        "location": edit_location, "status": edit_status, "notes": edit_notes,
                    })
                    flash("Equipamento atualizado.")
                    st.rerun()

        photos = equipment_photos(selected_equipment["id"])
        st.subheader("Fotos do equipamento", icon=":material/photo_library:")
        if photos:
            for start in range(0, len(photos), 2):
                photo_columns = st.columns(2)
                for offset, photo in enumerate(photos[start:start + 2]):
                    with photo_columns[offset].container(border=True):
                        st.image(bytes(photo["image_data"]), width="stretch")
                        st.caption(photo["caption"] or photo["filename"] or "Foto do equipamento")
                        render_delete_control(
                            "plant_equipment_photo", photo["id"],
                            f"foto {photo['filename'] or photo['id']}",
                        )
        else:
            st.caption("Nenhuma foto cadastrada para este equipamento.")

        if len(photos) < MAX_PHOTOS_PER_EQUIPMENT:
            photo_cycle_key = f"equipment_photo_cycle_{selected_equipment['id']}"
            photo_cycle = int(st.session_state.get(photo_cycle_key, 0))
            with st.expander("Adicionar fotos", icon=":material/add_a_photo:"):
                photo_caption = st.text_input("Legenda das novas fotos", key=f"equipment_photo_caption_{selected_equipment['id']}_{photo_cycle}")
                uploaded_photos = st.file_uploader(
                    "Escolher fotos da galeria",
                    type=["jpg", "jpeg", "png", "webp"],
                    accept_multiple_files=True,
                    max_upload_size=12,
                    key=f"equipment_photo_upload_{selected_equipment['id']}_{photo_cycle}",
                )
                camera_photo = st.camera_input(
                    "Ou tirar uma foto agora",
                    resolution="1080p",
                    key=f"equipment_camera_{selected_equipment['id']}_{photo_cycle}",
                )
                if st.button("Salvar novas fotos", type="primary", icon=":material/save:", key=f"save_equipment_photos_{selected_equipment['id']}_{photo_cycle}"):
                    pending_photos = list(uploaded_photos or []) + ([camera_photo] if camera_photo else [])
                    if not pending_photos:
                        st.error("Escolha ou tire pelo menos uma foto.")
                    elif len(photos) + len(pending_photos) > MAX_PHOTOS_PER_EQUIPMENT:
                        st.error(f"Cada equipamento aceita até {MAX_PHOTOS_PER_EQUIPMENT} fotos.")
                    else:
                        try:
                            for uploaded in pending_photos:
                                add_equipment_photo(selected_equipment["id"], uploaded.getvalue(), uploaded.name, photo_caption)
                            st.session_state[photo_cycle_key] = photo_cycle + 1
                            flash(f"{len(pending_photos)} foto(s) salva(s).")
                            st.rerun()
                        except (ValueError, OSError) as exc:
                            st.error(str(exc))

        render_delete_control(
            "plant_equipment", selected_equipment["id"],
            f"equipamento {selected_equipment['equipment_type']} {selected_equipment['model'] or ''}",
            extra_warning="As fotos vinculadas também serão excluídas.",
        )

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
        beneficiary_delete_map = {
            f"{row['name']} · UC {row['unit_code']}": row for row in beneficiaries
        }
        beneficiary_delete_label = st.selectbox(
            "Beneficiária para administrar",
            list(beneficiary_delete_map),
            key="beneficiary_delete_selector",
        )
        beneficiary_to_delete = beneficiary_delete_map[beneficiary_delete_label]
        render_delete_control(
            "beneficiary",
            beneficiary_to_delete["id"],
            f"beneficiária {beneficiary_to_delete['name']}",
        )
    else:
        st.info("Nenhuma unidade beneficiária cadastrada nesta usina.", icon=":material/info:")

with history:
    readings = query_df(
        """SELECT reference_month AS "Mês", generation_kwh AS "Geração", consumption_kwh AS "Consumo",
                  availability_pct AS "Disponibilidade", performance_ratio AS "Índice de performance",
                  downtime_hours AS "Indisponibilidade (h)", incidents AS "Ocorrências"
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
        """SELECT opened_at AS "Abertura", title AS "Ocorrência", category AS "Categoria",
                  severity AS "Severidade", status AS "Status", root_cause AS "Causa", resolution AS "Solução"
           FROM tickets WHERE plant_id=? ORDER BY opened_at DESC""",
        (plant_id,),
    )
    if tickets.empty:
        st.success("Nenhuma ocorrência registrada.", icon=":material/check_circle:")
    else:
        tickets["Abertura"] = tickets["Abertura"].map(date_br)
        st.dataframe(tickets, hide_index=True)
