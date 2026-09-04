from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import quote

import pandas as pd
import streamlit as st

from solar_crm.db import query, query_one
from solar_crm.inspection_documents import generate_inspection_pdf
from solar_crm.inspections import (
    INSPECTION_STATUSES,
    INSPECTION_URGENCIES,
    ITEM_STATUSES,
    add_inspection_photo,
    completion_score,
    create_inspection,
    ensure_inspection_schema,
    inspection_by_token,
    inspection_details,
    inspection_items,
    inspection_photos,
    inspection_share_url,
    update_inspection,
)
from solar_crm.ui import date_br, flash, page_intro, show_flash


INSPECTION_TYPES = [
    "Vistoria técnica",
    "Manutenção preventiva",
    "Manutenção corretiva",
    "Pré-instalação",
    "Comissionamento",
    "Garantia",
]
WEATHER_OPTIONS = ["Ensolarado", "Parcialmente nublado", "Nublado", "Chuva", "Não informado"]
ORIENTATIONS = ["Norte", "Nordeste", "Leste", "Sudeste", "Sul", "Sudoeste", "Oeste", "Noroeste", "Múltiplas águas", "Não medido"]
PHOTO_CATEGORIES = ["Vista geral", "Módulos", "Cobertura e estrutura", "Inversor", "Quadros e proteções", "Cabos e conectores", "Aterramento", "Falha encontrada", "Serviço executado", "Outras evidências"]

ensure_inspection_schema()


def _date_value(value: object, fallback: date | None = None) -> date:
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return fallback or date.today()


def _float_value(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _select_index(options: list[str], value: object, fallback: int = 0) -> int:
    return options.index(value) if value in options else fallback


def _show_saved_photos(inspection_id: int) -> None:
    photos = inspection_photos(inspection_id)
    if not photos:
        st.info("Nenhuma evidência fotográfica salva ainda.", icon=":material/add_a_photo:")
        return
    st.caption(f"{len(photos)} foto(s) armazenada(s) e incluída(s) no relatório.")
    for start in range(0, len(photos), 2):
        columns = st.columns(2)
        for offset, photo in enumerate(photos[start:start + 2]):
            with columns[offset].container(border=True):
                st.image(bytes(photo["image_data"]), width="stretch")
                st.caption(f"{photo['category']} · {photo.get('caption') or photo.get('filename') or 'Sem legenda'}")


def _render_field_form(inspection: dict) -> None:
    items = inspection_items(inspection["id"])
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grouped[item["category"]].append(item)

    with st.form(f"inspection_field_{inspection['id']}"):
        with st.expander("1. Atendimento e condições do local", expanded=True, icon=":material/location_on:"):
            inspection_type = st.selectbox(
                "Tipo de vistoria",
                INSPECTION_TYPES,
                index=_select_index(INSPECTION_TYPES, inspection.get("inspection_type")),
            )
            inspected_date = st.date_input("Data da visita", value=_date_value(inspection.get("inspected_at")))
            technician = st.text_input("Técnico responsável", value=inspection.get("technician") or "")
            contact_name = st.text_input("Responsável presente no local", value=inspection.get("contact_name") or "")
            contact_phone = st.text_input("Telefone do contato", value=inspection.get("contact_phone") or "")
            address = st.text_area("Endereço completo", value=inspection.get("address") or "", height=80)
            weather = st.selectbox("Condição do tempo", WEATHER_OPTIONS, index=_select_index(WEATHER_OPTIONS, inspection.get("weather"), 4))
            ambient_temperature = st.number_input("Temperatura ambiente (°C)", value=_float_value(inspection.get("ambient_temperature_c")), step=0.5)
            roof_type = st.text_input("Tipo de cobertura", value=inspection.get("roof_type") or "", placeholder="Ex.: telha cerâmica, fibrocimento, laje, solo")
            roof_condition = st.text_area("Condição da cobertura e estrutura", value=inspection.get("roof_condition") or "", height=80)
            access_condition = st.text_area("Acesso, trabalho em altura e restrições", value=inspection.get("access_condition") or "", height=80)

        with st.expander("2. Posição solar e sombreamento", icon=":material/wb_sunny:"):
            solar_orientation = st.selectbox("Orientação predominante dos módulos", ORIENTATIONS, index=_select_index(ORIENTATIONS, inspection.get("solar_orientation"), 8))
            azimuth_deg = st.number_input("Azimute medido (°)", min_value=0.0, max_value=360.0, value=_float_value(inspection.get("azimuth_deg")), step=1.0)
            tilt_deg = st.number_input("Inclinação dos módulos (°)", min_value=0.0, max_value=90.0, value=_float_value(inspection.get("tilt_deg")), step=1.0)
            shading_options = ["Nenhum", "Baixo", "Médio", "Alto", "Não medido"]
            shading_level = st.selectbox("Nível de sombreamento", shading_options, index=_select_index(shading_options, inspection.get("shading_level"), 4))
            shading_sources = st.text_area("Fontes, horários e áreas afetadas pelo sombreamento", value=inspection.get("shading_sources") or "", height=90)
            st.caption("Registre as coordenadas exibidas pelo GPS do celular. O navegador pode arredondar a posição.")
            latitude = st.number_input("Latitude", min_value=-90.0, max_value=90.0, value=_float_value(inspection.get("latitude")), step=0.000001, format="%.6f")
            longitude = st.number_input("Longitude", min_value=-180.0, max_value=180.0, value=_float_value(inspection.get("longitude")), step=0.000001, format="%.6f")

        with st.expander("3. Checklist técnico", icon=":material/fact_check:"):
            st.caption("Marque cada ponto verificado. Itens pendentes ficam destacados no relatório.")
            checklist_values = []
            for category, category_items in grouped.items():
                st.markdown(f"**{category}**")
                for item in category_items:
                    key_root = f"inspection_{inspection['id']}_item_{item['id']}"
                    item_status = st.selectbox(
                        item["item"],
                        ITEM_STATUSES,
                        index=_select_index(ITEM_STATUSES, item.get("status")),
                        key=f"{key_root}_status",
                    )
                    item_notes = st.text_input(
                        f"Observação · {item['item']}",
                        value=item.get("notes") or "",
                        key=f"{key_root}_notes",
                        label_visibility="collapsed",
                        placeholder="Observação opcional",
                    )
                    checklist_values.append({**item, "status": item_status, "notes": item_notes})
                st.divider()

        with st.expander("4. Medições elétricas e desempenho", icon=":material/electric_meter:"):
            dc_voltage = st.number_input("Tensão CC (V)", min_value=0.0, value=_float_value(inspection.get("dc_voltage_v")), step=0.1)
            dc_current = st.number_input("Corrente CC (A)", min_value=0.0, value=_float_value(inspection.get("dc_current_a")), step=0.1)
            ac_voltage = st.number_input("Tensão CA (V)", min_value=0.0, value=_float_value(inspection.get("ac_voltage_v")), step=0.1)
            ac_current = st.number_input("Corrente CA (A)", min_value=0.0, value=_float_value(inspection.get("ac_current_a")), step=0.1)
            insulation = st.number_input("Resistência de isolação (MΩ)", min_value=0.0, value=_float_value(inspection.get("insulation_mohm")), step=0.1)
            grounding = st.number_input("Resistência de aterramento (Ω)", min_value=0.0, value=_float_value(inspection.get("grounding_ohm")), step=0.1)
            generation_power = st.number_input("Potência gerada no momento (kW)", min_value=0.0, value=_float_value(inspection.get("generation_power_kw")), step=0.1)
            inverter_alarms = st.text_area("Alarmes e eventos do inversor", value=inspection.get("inverter_alarms") or "", height=80)

        with st.expander("5. Diagnóstico e encaminhamento", icon=":material/engineering:"):
            safety_risks = st.text_area("Riscos e condições de segurança", value=inspection.get("safety_risks") or "", height=100)
            findings = st.text_area("Falhas, anomalias e constatações", value=inspection.get("findings") or "", height=130)
            actions = st.text_area("Serviços executados durante a visita", value=inspection.get("actions_performed") or "", height=110)
            recommendations = st.text_area("Recomendações e correções necessárias", value=inspection.get("recommendations") or "", height=110)
            materials = st.text_area("Materiais, peças e ferramentas necessárias", value=inspection.get("materials_needed") or "", height=90)
            urgency = st.selectbox("Urgência", INSPECTION_URGENCIES, index=_select_index(INSPECTION_URGENCIES, inspection.get("urgency")))
            needs_return = st.toggle("Programar retorno", value=bool(inspection.get("follow_up_date")))
            follow_up = st.date_input(
                "Data sugerida para retorno",
                value=_date_value(inspection.get("follow_up_date"), date.today() + timedelta(days=7)),
                disabled=not needs_return,
            )
            acknowledgement = st.text_area("Ciência do responsável do cliente", value=inspection.get("client_acknowledgement") or "", height=90, placeholder="Ex.: Cliente informado sobre o desligamento necessário e orçamento complementar.")
            status = st.selectbox("Status final da vistoria", INSPECTION_STATUSES, index=_select_index(INSPECTION_STATUSES, inspection.get("status"), 1))

        with st.expander("6. Fotos e evidências", expanded=True, icon=":material/photo_camera:"):
            photo_category = st.selectbox("Categoria da foto tirada agora", PHOTO_CATEGORIES)
            camera_photo = st.camera_input("Tirar foto no local", resolution="1080p", width="stretch")
            camera_caption = st.text_input("Legenda da foto", placeholder="Ex.: Conector MC4 da string 3 com aquecimento")
            uploaded_photos = st.file_uploader(
                "Adicionar outras fotos da galeria",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                max_upload_size=12,
            )
            st.caption("O SolarOS reduz as imagens antes de armazenar. Limite de 20 fotos por vistoria.")

        submitted = st.form_submit_button("Salvar vistoria e evidências", type="primary", icon=":material/save:", width="stretch")
        if submitted:
            try:
                update_inspection(inspection["id"], {
                    "inspection_type": inspection_type,
                    "status": status,
                    "urgency": urgency,
                    "inspected_at": inspected_date.isoformat(),
                    "technician": technician,
                    "contact_name": contact_name,
                    "contact_phone": contact_phone,
                    "address": address,
                    "weather": weather,
                    "ambient_temperature_c": ambient_temperature,
                    "roof_type": roof_type,
                    "roof_condition": roof_condition,
                    "access_condition": access_condition,
                    "latitude": latitude,
                    "longitude": longitude,
                    "solar_orientation": solar_orientation,
                    "azimuth_deg": azimuth_deg,
                    "tilt_deg": tilt_deg,
                    "shading_level": shading_level,
                    "shading_sources": shading_sources,
                    "dc_voltage_v": dc_voltage,
                    "dc_current_a": dc_current,
                    "ac_voltage_v": ac_voltage,
                    "ac_current_a": ac_current,
                    "insulation_mohm": insulation,
                    "grounding_ohm": grounding,
                    "generation_power_kw": generation_power,
                    "inverter_alarms": inverter_alarms,
                    "safety_risks": safety_risks,
                    "findings": findings,
                    "actions_performed": actions,
                    "recommendations": recommendations,
                    "materials_needed": materials,
                    "follow_up_date": follow_up.isoformat() if needs_return else None,
                    "client_acknowledgement": acknowledgement,
                }, checklist_values)
                if camera_photo:
                    add_inspection_photo(inspection["id"], camera_photo.getvalue(), camera_photo.name, photo_category, camera_caption)
                for uploaded in uploaded_photos or []:
                    add_inspection_photo(inspection["id"], uploaded.getvalue(), uploaded.name, "Outras evidências", uploaded.name)
                st.success("Vistoria salva com sucesso.", icon=":material/check_circle:")
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(str(exc), icon=":material/error:")


token = str(st.query_params.get("inspection") or "").strip()
if token:
    current = inspection_by_token(token)
    if not current:
        st.error("Este link de vistoria é inválido ou não está mais disponível.", icon=":material/link_off:")
        st.stop()
    page_intro("Ficha de campo otimizada para celular, com checklist, medições, fotos e relatório técnico.")
    st.subheader(f"{current['number']} · {current['client_name']}", icon=":material/fact_check:")
    with st.container(horizontal=True):
        st.metric("Status", current["status"], border=True)
        st.metric("Checklist", f"{completion_score(current['id'])}%", border=True)
        st.metric("Fotos", len(inspection_photos(current["id"])), border=True)
    with st.container(border=True):
        st.markdown(f"**Usina / UC:** {current.get('plant_name') or 'Instalação do cliente'} · {current.get('unit_code') or '-'}")
        st.markdown(f"**Endereço:** {current['address']}")
        st.markdown(f"**Contato:** {current.get('contact_name') or '-'} · {current.get('contact_phone') or '-'}")
        st.markdown(f"[Abrir rota no mapa](https://www.google.com/maps/search/?api=1&query={quote(current['address'])})")
    _render_field_form(current)
    st.subheader("Evidências salvas", icon=":material/photo_library:")
    _show_saved_photos(current["id"])
    st.download_button(
        "Baixar relatório da vistoria em PDF",
        generate_inspection_pdf(current["id"]),
        file_name=f"{current['number'].lower()}.pdf",
        mime="application/pdf",
        icon=":material/picture_as_pdf:",
        width="stretch",
    )
    st.stop()


page_intro("Planeje a visita, envie a ficha ao técnico e gere um relatório fotográfico completo para o cliente.")
show_flash()

clients = query("SELECT id, name, contact_name, phone, address, city, state FROM clients WHERE status='Ativo' ORDER BY name")
plants = query("SELECT id, client_id, name, unit_code, address FROM plants WHERE status!='Desativada' ORDER BY name")
orders = query("SELECT id, client_id, plant_id, number, title, address FROM service_orders WHERE status NOT IN ('Concluída','Cancelada') ORDER BY scheduled_date, id DESC")
settings = query_one("SELECT share_base_url FROM settings WHERE id=1")
inspections = query(
    """SELECT si.*, c.name AS client_name, COALESCE(p.name,'Instalação do cliente') AS plant_name,
              COALESCE((SELECT COUNT(*) FROM inspection_photos ip WHERE ip.inspection_id=si.id), 0) AS photo_count
       FROM site_inspections si JOIN clients c ON c.id=si.client_id
       LEFT JOIN plants p ON p.id=si.plant_id
       ORDER BY CASE si.status WHEN 'Concluída' THEN 2 ELSE 1 END, si.inspected_at DESC, si.id DESC"""
)

open_inspections = [row for row in inspections if row["status"] != "Concluída"]
with st.container(horizontal=True):
    st.metric("Vistorias abertas", len(open_inspections), border=True)
    st.metric("Concluídas", sum(row["status"] == "Concluída" for row in inspections), border=True)
    st.metric("Requerem retorno", sum(row["status"] == "Requer retorno" for row in inspections), border=True)
    st.metric("Fotos registradas", sum(int(row["photo_count"]) for row in inspections), border=True)

if clients:
    with st.container(horizontal=True, horizontal_alignment="right"):
        new_inspection = st.popover("Nova vistoria", icon=":material/add_location_alt:")
    with new_inspection:
        client_map = {row["name"]: row for row in clients}
        selected_client_name = st.selectbox("Cliente", list(client_map), key="inspection_client")
        client = client_map[selected_client_name]
        client_plants = [row for row in plants if row["client_id"] == client["id"]]
        plant_map = {"Instalação sem usina cadastrada": None, **{f"{row['name']} · {row['unit_code'] or '-'}": row for row in client_plants}}
        selected_plant_name = st.selectbox("Usina", list(plant_map), key="inspection_plant")
        plant = plant_map[selected_plant_name]
        client_orders = [row for row in orders if row["client_id"] == client["id"] and (not plant or row.get("plant_id") in {None, plant["id"]})]
        order_map = {"Sem ordem de serviço vinculada": None, **{f"{row['number']} · {row['title']}": row for row in client_orders}}
        selected_order_name = st.selectbox("Ordem de serviço", list(order_map), key="inspection_order")
        selected_order = order_map[selected_order_name]
        default_address = (plant.get("address") if plant else None) or (selected_order.get("address") if selected_order else None) or ", ".join(filter(None, [client.get("address"), client.get("city"), client.get("state")]))
        with st.form("new_inspection", clear_on_submit=True):
            inspection_type = st.selectbox("Tipo", INSPECTION_TYPES)
            inspection_date = st.date_input("Data programada", value=date.today())
            technician = st.text_input("Técnico responsável")
            address = st.text_area("Endereço", value=default_address, height=80)
            contact_name = st.text_input("Contato no local", value=client.get("contact_name") or "")
            contact_phone = st.text_input("Telefone", value=client.get("phone") or "")
            urgency = st.selectbox("Urgência", INSPECTION_URGENCIES)
            if st.form_submit_button("Criar ficha de vistoria", type="primary", icon=":material/save:", width="stretch"):
                try:
                    inspection_id = create_inspection({
                        "client_id": client["id"],
                        "plant_id": plant["id"] if plant else None,
                        "service_order_id": selected_order["id"] if selected_order else None,
                        "inspection_type": inspection_type,
                        "status": "Rascunho",
                        "urgency": urgency,
                        "inspected_at": inspection_date.isoformat(),
                        "technician": technician,
                        "contact_name": contact_name,
                        "contact_phone": contact_phone,
                        "address": address,
                    })
                    st.session_state["selected_inspection_id"] = inspection_id
                    flash("Ficha de vistoria criada. O link de campo já está disponível.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
else:
    st.warning("Cadastre um cliente antes de programar uma vistoria.", icon=":material/warning:")

if inspections:
    st.subheader("Histórico de vistorias", icon=":material/history:")
    frame = pd.DataFrame(inspections)[["number", "inspected_at", "client_name", "plant_name", "inspection_type", "urgency", "status", "photo_count"]]
    frame.columns = ["Número", "Data", "Cliente", "Usina", "Tipo", "Urgência", "Status", "Fotos"]
    frame["Data"] = frame["Data"].map(date_br)
    st.dataframe(frame, hide_index=True, width="stretch", column_config={"Cliente": st.column_config.TextColumn(pinned=True)})

    inspection_map = {f"{row['number']} · {row['client_name']} · {date_br(row['inspected_at'])}": row for row in inspections}
    selected_default = 0
    preferred = st.session_state.pop("selected_inspection_id", None)
    if preferred:
        for index, row in enumerate(inspections):
            if row["id"] == preferred:
                selected_default = index
                break
    selected_label = st.selectbox("Abrir vistoria", list(inspection_map), index=selected_default)
    selected = inspection_details(inspection_map[selected_label]["id"])
    share_url = inspection_share_url(selected, settings.get("share_base_url") if settings else "")
    with st.container(border=True):
        st.subheader(f"{selected['number']} · ficha de campo", icon=":material/share:")
        st.text_input("Link individual para o técnico", value=share_url, key=f"inspection_share_{selected['id']}")
        st.caption("O link abre diretamente a vistoria no celular. Quem o receber poderá preencher a ficha e anexar fotos.")
        whatsapp_text = quote(f"Vistoria {selected['number']} - {selected['client_name']}\n{share_url}")
        st.markdown(f"[Enviar link pelo WhatsApp](https://wa.me/?text={whatsapp_text})")
        with st.container(horizontal=True):
            st.download_button(
                "Baixar relatório em PDF",
                generate_inspection_pdf(selected["id"]),
                file_name=f"{selected['number'].lower()}.pdf",
                mime="application/pdf",
                icon=":material/picture_as_pdf:",
            )
            st.link_button("Abrir ficha de campo", share_url, icon=":material/open_in_new:")
    with st.expander("Editar a ficha neste painel", icon=":material/edit_note:"):
        _render_field_form(selected)
    with st.expander("Evidências fotográficas", icon=":material/photo_library:"):
        _show_saved_photos(selected["id"])
else:
    st.info("Nenhuma vistoria cadastrada. Crie a primeira ficha para enviar à equipe de campo.", icon=":material/info:")
