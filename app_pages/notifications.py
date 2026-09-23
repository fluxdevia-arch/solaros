from datetime import date

import pandas as pd
import streamlit as st

from solar_crm.db import query
from solar_crm.notifications import (
    AUDIENCES,
    SEVERITIES,
    create_manual_notification,
    notification_counts,
    notifications_for_role,
    refresh_automatic_notifications,
    set_notification_status,
    whatsapp_url,
)
from solar_crm.ui import date_br, datetime_br, flash, page_intro, show_flash


page_intro("Acompanhe vencimentos, preventivas, atividades, garantias, falhas e leituras pendentes em um só lugar.")
show_flash()

role = st.session_state.get("app_user", {}).get("role", "Administrador")
refresh_automatic_notifications()
counts = notification_counts(role)

with st.container(horizontal=True):
    st.metric("Novas", counts["new"], border=True)
    st.metric("Críticas", counts["critical"], border=True)
    st.metric("Pendências visíveis", counts["total"], border=True)
    if st.button("Atualizar alertas", icon=":material/refresh:"):
        refresh_automatic_notifications()
        flash("Notificações atualizadas com os dados mais recentes.")
        st.rerun()

clients = query("SELECT id, name, contact_name, phone, email FROM clients WHERE status='Ativo' ORDER BY name")
with st.container(horizontal=True, horizontal_alignment="right"):
    new_notification = st.popover("Nova notificação", icon=":material/add_alert:")

with new_notification:
    client_map = {"Aviso interno, sem cliente": None, **{row["name"]: row for row in clients}}
    selected_client = client_map[st.selectbox("Destinatário", list(client_map))]
    with st.form("manual_notification", clear_on_submit=True):
        title = st.text_input("Título", placeholder="Ex.: Relatório mensal disponível")
        message = st.text_area("Mensagem", placeholder="Escreva uma mensagem objetiva para a equipe ou para o cliente.")
        category = st.selectbox("Categoria", ["Geral", "Financeiro", "Operação", "Preventiva", "Leitura", "Comercial"])
        severity = st.selectbox("Prioridade", SEVERITIES, index=1)
        audience = st.selectbox("Perfil que visualizará", AUDIENCES)
        has_due_date = st.checkbox("Definir data limite")
        due_date = st.date_input("Data limite", value=date.today(), disabled=not has_due_date)
        if st.form_submit_button("Criar notificação", type="primary", icon=":material/notifications_active:"):
            try:
                create_manual_notification({
                    "title": title,
                    "message": message,
                    "category": category,
                    "severity": severity,
                    "audience": audience,
                    "client_id": selected_client["id"] if selected_client else None,
                    "due_date": due_date.isoformat() if has_due_date else None,
                    "recipient_name": (selected_client or {}).get("contact_name") or (selected_client or {}).get("name"),
                    "recipient_phone": (selected_client or {}).get("phone"),
                    "recipient_email": (selected_client or {}).get("email"),
                })
                flash("Notificação criada.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

all_active = notifications_for_role(role)
category_options = sorted({row["category"] for row in all_active})
with st.container(border=True):
    st.subheader("Filtros", icon=":material/filter_alt:")
    priorities = st.pills("Prioridade", SEVERITIES, selection_mode="multi")
    categories = st.multiselect("Categorias", category_options, placeholder="Todas as categorias")
    only_new = st.toggle("Mostrar somente novas")

filtered = [
    row for row in all_active
    if (not priorities or row["severity"] in priorities)
    and (not categories or row["category"] in categories)
    and (not only_new or row["status"] == "Nova")
]

if not filtered:
    st.success("Nenhuma notificação pendente para os filtros selecionados.", icon=":material/check_circle:")
else:
    st.subheader("Central de alertas", icon=":material/notifications:")
    severity_icons = {
        "Crítica": ":material/error:",
        "Alta": ":material/priority_high:",
        "Média": ":material/notification_important:",
        "Baixa": ":material/info:",
    }
    for item in filtered:
        with st.container(border=True):
            st.subheader(item["title"], icon=severity_icons.get(item["severity"], ":material/notifications:"))
            st.caption(
                f"{item['severity']} · {item['category']} · {item['origin']}"
                + (f" · prazo {date_br(item['due_date'])}" if item.get("due_date") else "")
            )
            st.write(item["message"])
            if item.get("client_name") or item.get("plant_name"):
                st.caption(" · ".join(filter(None, [item.get("client_name"), item.get("plant_name")])))
            with st.container(horizontal=True):
                if item["status"] == "Nova" and st.button(
                    "Marcar como lida", key=f"read_notification_{item['id']}", icon=":material/done:"
                ):
                    set_notification_status(item["id"], "Lida")
                    st.rerun()
                if st.button("Arquivar", key=f"archive_notification_{item['id']}", icon=":material/archive:"):
                    set_notification_status(item["id"], "Arquivada")
                    st.rerun()
                whats_url = whatsapp_url(item)
                if whats_url:
                    st.link_button("Enviar no WhatsApp", whats_url, icon=":material/chat:")
            if item.get("recipient_email"):
                st.caption(f"E-mail do destinatário: {item['recipient_email']}")

history = notifications_for_role(role, include_archived=True)
history = [row for row in history if row["status"] in {"Arquivada", "Resolvida"}]
history_panel = st.expander("Histórico de alertas", icon=":material/history:", on_change="rerun")
if history_panel.open:
    with history_panel:
        if history:
            frame = pd.DataFrame([
                {
                    "Criada em": datetime_br(row["created_at"]),
                    "Título": row["title"],
                    "Categoria": row["category"],
                    "Prioridade": row["severity"],
                    "Cliente": row.get("client_name") or "-",
                    "Status": row["status"],
                }
                for row in history
            ])
            st.dataframe(frame, hide_index=True, width="stretch")
        else:
            st.caption("Nenhuma notificação arquivada ou resolvida.")

st.caption("O envio pelo WhatsApp abre a conversa com a mensagem pronta. O disparo totalmente automático exigirá uma integração oficial de mensagens.")
