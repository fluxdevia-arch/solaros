from datetime import date, datetime, timedelta
from urllib.parse import quote

import pandas as pd
import streamlit as st

from solar_crm.db import query, query_df, query_one
from solar_crm.document_cache import service_order_pdf
from solar_crm.sharing import resolve_share_base_url
from solar_crm.ui import date_br, flash, page_intro, render_delete_control, show_flash
from solar_crm.workflow import (
    SERVICE_ORDER_STATUSES,
    create_service_order,
    regenerate_service_order_token,
    service_order_by_token,
    service_order_share_url,
    update_service_order,
)


token = str(st.query_params.get("os") or "").strip()
if token:
    order = service_order_by_token(token)
    if not order:
        st.error("Este link de ordem de serviço é inválido ou não está mais disponível.", icon=":material/link_off:")
        st.stop()

    page_intro("Ficha de campo com instruções, endereço, equipamentos e registro da execução.")
    st.subheader(f"{order['number']} · {order['title']}", icon=":material/assignment:")
    with st.container(horizontal=True):
        st.metric("Status", order["status"], border=True)
        st.metric("Prioridade", order["priority"], border=True)
        st.metric("Agendamento", date_br(order["scheduled_date"]), border=True)
    with st.container(border=True):
        st.markdown(f"**Cliente:** {order['client_name']}")
        st.markdown(f"**Usina / UC:** {order.get('plant_name') or 'Serviço geral'} · {order.get('unit_code') or '-'}")
        st.markdown(f"**Endereço:** {order['address']}")
        st.markdown(f"**Contato:** {order.get('contact_name') or '-'} · {order.get('contact_phone') or '-'}")
        map_url = f"https://www.google.com/maps/search/?api=1&query={quote(order['address'])}"
        st.markdown(f"[Abrir endereço no mapa]({map_url})")
    left, right = st.columns(2)
    with left.container(border=True, height="stretch"):
        st.subheader("Serviço a executar", icon=":material/build:")
        st.write(order["work_description"])
        st.subheader("Segurança e acesso", icon=":material/health_and_safety:")
        st.write(order.get("safety_instructions") or "Sem instruções adicionais.")
    with right.container(border=True, height="stretch"):
        st.subheader("Materiais previstos", icon=":material/construction:")
        st.write(order.get("materials") or "Sem materiais registrados.")
        st.caption(f"Inversor: {order.get('inverter') or '-'}")
        st.caption(f"Módulos: {order.get('modules') or '-'}")

    with st.form("field_order_update"):
        st.subheader("Atualização da equipe", icon=":material/edit_note:")
        field_assignee = st.text_input("Técnico responsável", value=order.get("assignee") or "")
        allowed_field_statuses = ["Em deslocamento", "Em execução", "Concluída", "Impedida"]
        default_status = order["status"] if order["status"] in allowed_field_statuses else "Em execução"
        field_status = st.segmented_control("Status", allowed_field_statuses, default=default_status)
        completion_notes = st.text_area("Serviços realizados, medições e pendências", value=order.get("completion_notes") or "")
        if st.form_submit_button("Salvar atualização", type="primary", icon=":material/save:"):
            update_service_order(order["id"], field_status, completion_notes, field_assignee)
            st.success("Ordem de serviço atualizada.", icon=":material/check_circle:")
            st.rerun()
    st.download_button(
        "Baixar ordem de serviço em PDF",
        service_order_pdf(order["id"], str(order.get("updated_at") or "")),
        file_name=f"{order['number'].lower()}.pdf",
        mime="application/pdf",
        icon=":material/download:",
    )
    st.stop()


page_intro("Crie, programe e compartilhe ordens de serviço completas com a equipe de campo.")
show_flash()

clients = query("SELECT id, name, contact_name, phone, address, city, state FROM clients WHERE status='Ativo' ORDER BY name")
plants = query("SELECT id, client_id, name, unit_code, address FROM plants WHERE status!='Desativada' ORDER BY name")
settings = query_one("SELECT share_base_url FROM settings WHERE id=1")

orders = query(
    """SELECT so.*, c.name AS client_name, COALESCE(p.name,'Serviço geral') AS plant_name
       FROM service_orders so JOIN clients c ON c.id=so.client_id
       LEFT JOIN plants p ON p.id=so.plant_id
       ORDER BY CASE so.status WHEN 'Concluída' THEN 2 WHEN 'Cancelada' THEN 3 ELSE 1 END,
                so.scheduled_date, so.id DESC"""
)
open_orders = [row for row in orders if row["status"] not in {"Concluída", "Cancelada"}]
today = date.today().isoformat()
delayed = sum(1 for row in open_orders if row.get("scheduled_date") and row["scheduled_date"] < today)

with st.container(horizontal=True):
    st.metric("Ordens abertas", len(open_orders), border=True)
    st.metric("Agendadas", sum(1 for row in open_orders if row["status"] == "Agendada"), border=True)
    st.metric("Em campo", sum(1 for row in open_orders if row["status"] in {"Em deslocamento", "Em execução"}), border=True)
    st.metric("Atrasadas", delayed, border=True)

if not clients:
    st.warning("Cadastre um cliente antes de criar ordens de serviço.", icon=":material/warning:")
else:
    with st.container(horizontal=True, horizontal_alignment="right"):
        new_order = st.popover("Nova ordem de serviço", icon=":material/add_task:")

    with new_order:
        client_map = {row["name"]: row for row in clients}
        selected_client_name = st.selectbox("Cliente", list(client_map), key="os_client")
        client = client_map[selected_client_name]
        client_plants = [row for row in plants if row["client_id"] == client["id"]]
        plant_map = {"Serviço geral do cliente": None, **{f"{row['name']} · {row['unit_code'] or '-'}": row for row in client_plants}}
        selected_plant_name = st.selectbox("Usina", list(plant_map), key="os_plant")
        plant = plant_map[selected_plant_name]
        default_address = (plant.get("address") if plant else None) or ", ".join(filter(None, [client.get("address"), client.get("city"), client.get("state")]))
        with st.form("new_service_order", clear_on_submit=True):
            title = st.text_input("Título", placeholder="Ex.: Inspeção do inversor 2")
            service_type = st.selectbox("Tipo", ["Manutenção preventiva", "Manutenção corretiva", "Limpeza", "Inspeção técnica", "Comissionamento", "Consultoria em campo", "Outro"])
            c1, c2 = st.columns(2)
            priority = c1.selectbox("Prioridade", ["Baixa", "Média", "Alta", "Crítica"], index=1)
            scheduled_date = c2.date_input("Agendamento", value=date.today() + timedelta(days=2))
            assignee = st.text_input("Equipe / responsável")
            address = st.text_input("Endereço", value=default_address)
            c3, c4 = st.columns(2)
            contact_name = c3.text_input("Contato no local", value=client.get("contact_name") or "")
            contact_phone = c4.text_input("Telefone", value=client.get("phone") or "")
            work_description = st.text_area("O que deve ser feito", placeholder="Descreva o defeito, as verificações e o resultado esperado.")
            safety = st.text_area("Segurança, acesso e desligamentos")
            materials = st.text_area("Materiais e ferramentas previstos")
            if st.form_submit_button("Emitir ordem de serviço", type="primary", icon=":material/save:"):
                try:
                    create_service_order({
                        "client_id": client["id"], "plant_id": plant["id"] if plant else None,
                        "title": title, "service_type": service_type, "priority": priority,
                        "status": "Agendada", "requested_at": datetime.now().isoformat(timespec="seconds"),
                        "scheduled_date": scheduled_date.isoformat(), "assignee": assignee,
                        "address": address, "contact_name": contact_name, "contact_phone": contact_phone,
                        "work_description": work_description, "safety_instructions": safety, "materials": materials,
                    })
                    flash("Ordem de serviço emitida.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

if orders:
    st.subheader("Ordens de serviço", icon=":material/assignment:")
    status_filter = st.pills("Status", SERVICE_ORDER_STATUSES, default=["Aberta", "Agendada", "Em deslocamento", "Em execução", "Impedida"], selection_mode="multi")
    filtered = [row for row in orders if not status_filter or row["status"] in status_filter]
    frame = pd.DataFrame(filtered)[["number", "scheduled_date", "title", "client_name", "plant_name", "priority", "status", "assignee"]]
    frame.columns = ["Número", "Agendamento", "Serviço", "Cliente", "Usina", "Prioridade", "Status", "Responsável"]
    frame["Agendamento"] = frame["Agendamento"].map(date_br)
    st.dataframe(frame, hide_index=True, column_config={"Serviço": st.column_config.TextColumn(pinned=True)})

    order_map = {f"{row['number']} · {row['client_name']} · {row['title']}": row for row in orders}
    selected_order_label = st.selectbox("Abrir ordem de serviço", list(order_map), key="os_selected")
    selected_order = order_map[selected_order_label]
    share_base_url = resolve_share_base_url(
        settings.get("share_base_url") if settings else "",
        str(st.context.url),
    )
    share_url = service_order_share_url(selected_order, share_base_url)
    with st.container(border=True):
        st.subheader(f"{selected_order['number']} · envio e impressão", icon=":material/share:")
        st.text_input("Link individual para a equipe", value=share_url, key="os_share_link")
        st.caption("Quem receber este link poderá consultar a O.S. e atualizar a execução. Configure a URL de compartilhamento em Configurações.")
        whatsapp_text = quote(f"Ordem de serviço {selected_order['number']} - {selected_order['title']}\n{share_url}")
        st.markdown(f"[Enviar pelo WhatsApp](https://wa.me/?text={whatsapp_text})")
        with st.container(horizontal=True):
            st.download_button(
                "Baixar PDF para imprimir",
                service_order_pdf(selected_order["id"], str(selected_order.get("updated_at") or "")),
                file_name=f"{selected_order['number'].lower()}.pdf",
                mime="application/pdf",
                icon=":material/download:",
            )
            if st.button("Gerar novo link", icon=":material/link_off:"):
                regenerate_service_order_token(selected_order["id"])
                flash("Novo link gerado. O link anterior foi invalidado.")
                st.rerun()
    with st.expander("Atualizar ordem de serviço", icon=":material/edit:"):
        with st.form("admin_order_update"):
            new_status = st.selectbox("Status", SERVICE_ORDER_STATUSES, index=SERVICE_ORDER_STATUSES.index(selected_order["status"]))
            new_assignee = st.text_input("Responsável", value=selected_order.get("assignee") or "")
            notes = st.text_area("Registro da execução", value=selected_order.get("completion_notes") or "")
            if st.form_submit_button("Salvar alterações", type="primary", icon=":material/save:"):
                update_service_order(selected_order["id"], new_status, notes, new_assignee)
                flash("Ordem de serviço atualizada.")
                st.rerun()
    render_delete_control(
        "service_order",
        selected_order["id"],
        f"ordem de serviço {selected_order['number']}",
    )
else:
    st.info("Nenhuma ordem de serviço emitida.", icon=":material/info:")
