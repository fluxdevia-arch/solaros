import importlib
from datetime import datetime, timedelta

import streamlit as st

from solar_crm import db as db_module

# Streamlit can hot-reload the entrypoint while keeping imported modules alive.
# Reload an older database module before running a newly deployed migration.
if int(getattr(db_module, "SCHEMA_VERSION", 0)) < 21:
    db_module = importlib.reload(db_module)

from solar_crm import auth as auth_module

# The hosted process can keep the previous auth module alive while replacing
# this entrypoint. Reload it when a deployment introduces role management.
if not hasattr(auth_module, "current_app_user"):
    auth_module = importlib.reload(auth_module)

current_app_user = auth_module.current_app_user
render_user_sidebar = auth_module.render_user_sidebar
require_login = auth_module.require_login
from solar_crm.branding import configured_app_name, configured_logo
from solar_crm.config import seed_demo_data

SCHEMA_VERSION = db_module.SCHEMA_VERSION
database_cache_key = db_module.database_cache_key
init_db = db_module.init_db
query_one = db_module.query_one
using_postgres = db_module.using_postgres

st.set_page_config(
    page_title="GRID Engenharia",
    page_icon=":material/solar_power:",
    layout="wide",
    initial_sidebar_state="auto",
)

field_order_mode = bool(str(st.query_params.get("os") or "").strip())
field_inspection_mode = bool(str(st.query_params.get("inspection") or "").strip())
field_mode = field_order_mode or field_inspection_mode


@st.cache_resource(show_spinner=False)
def prepare_database(schema_version: int, seed: bool, database_identity: str) -> int:
    """Initialize tables once per process and again whenever the schema changes."""
    init_db(seed=seed)
    return schema_version


prepare_database(SCHEMA_VERSION, seed_demo_data(), database_cache_key())

app_settings = query_one("SELECT app_name, brand_logo FROM settings WHERE id=1")
active_app_name = configured_app_name(app_settings)
active_logo = configured_logo(app_settings)
authenticated = False if field_mode else require_login(active_app_name, active_logo)

if not field_mode:
    app_user = current_app_user()
    st.session_state["app_user"] = app_user
    if not app_user.get("active"):
        st.error("Seu login foi reconhecido, mas esta conta ainda não foi liberada no sistema.", icon=":material/person_alert:")
        st.write("Peça a um administrador para cadastrar seu e-mail em **Configurações > Usuários e permissões**.")
        if st.button("Sair", icon=":material/logout:"):
            st.logout()
        st.stop()
else:
    app_user = {"role": "Acesso de campo", "active": 1}

if field_mode:
    st.logo(active_logo, size="large")

st.session_state.setdefault("selected_client_id", None)
st.session_state.setdefault("selected_plant_id", None)

if field_order_mode:
    field_page = st.navigation(
        [st.Page("app_pages/service_orders.py", title="Ordem de serviço", icon=":material/assignment:", url_path="service-orders")],
        position="hidden",
    )
    st.title(field_page.title, icon=field_page.icon)
    field_page.run()
    st.stop()

if field_inspection_mode:
    field_page = st.navigation(
        [st.Page("app_pages/inspections.py", title="Vistoria técnica", icon=":material/fact_check:", url_path="inspections")],
        position="hidden",
    )
    st.title(field_page.title, icon=field_page.icon)
    field_page.run()
    st.stop()

notification_count = 0
try:
    from solar_crm.notifications import notification_counts, refresh_automatic_notifications

    last_refresh = st.session_state.get("notifications_refreshed_at")
    if not isinstance(last_refresh, datetime) or datetime.now() - last_refresh >= timedelta(minutes=5):
        refresh_automatic_notifications()
        st.session_state["notifications_refreshed_at"] = datetime.now()
    notification_count = notification_counts(role=app_user.get("role") or "Administrador")["new"]
except Exception:
    # Notification failures must never block operational access to the CRM.
    notification_count = 0

notification_title = f"Notificações ({notification_count})" if notification_count else "Notificações"

all_pages = {
    "Gestão": [
        st.Page("app_pages/dashboard.py", title="Visão geral", icon=":material/space_dashboard:"),
        st.Page("app_pages/notifications.py", title=notification_title, icon=":material/notifications:"),
        st.Page("app_pages/clients.py", title="Clientes e contratos", icon=":material/groups:"),
        st.Page("app_pages/plants.py", title="Usinas", icon=":material/solar_power:"),
    ],
    "Pós-venda": [
        st.Page("app_pages/readings.py", title="Leituras e faturas", icon=":material/bolt:"),
        st.Page("app_pages/bill_audits.py", title="Auditoria de faturas", icon=":material/receipt_long:"),
        st.Page("app_pages/compensation_statements.py", title="Compensação de energia", icon=":material/account_tree:"),
        st.Page("app_pages/integrations.py", title="Integrações", icon=":material/api:"),
        st.Page("app_pages/inverter_diagnostics.py", title="Diagnóstico por Excel", icon=":material/analytics:"),
        st.Page("app_pages/equipment_analysis.py", title="Análise de equipamentos", icon=":material/vital_signs:"),
        st.Page("app_pages/fault_guide.py", title="Guia de falhas", icon=":material/troubleshoot:"),
        st.Page("app_pages/operations.py", title="Operação e agenda", icon=":material/build:"),
        st.Page("app_pages/service_orders.py", title="Ordens de serviço", icon=":material/assignment:"),
        st.Page("app_pages/inspections.py", title="Vistorias", icon=":material/fact_check:"),
        st.Page("app_pages/maintenance_inventory.py", title="Preventivas e estoque", icon=":material/inventory_2:"),
        st.Page("app_pages/reports.py", title="Relatórios", icon=":material/description:"),
    ],
    "Engenharia": [
        st.Page("app_pages/sizing.py", title="Dimensionamento", icon=":material/electrical_services:"),
    ],
    "Comercial": [
        st.Page("app_pages/pipeline.py", title="Kanban comercial", icon=":material/view_kanban:"),
        st.Page("app_pages/proposals.py", title="Propostas", icon=":material/request_quote:"),
        st.Page("app_pages/cash.py", title="Caixa", icon=":material/point_of_sale:"),
        st.Page("app_pages/pricing.py", title="Precificação", icon=":material/calculate:"),
        st.Page("app_pages/service_contracts.py", title="Contratos de serviço", icon=":material/description:"),
        st.Page("app_pages/settings.py", title="Configurações", icon=":material/settings:"),
    ],
}

role = app_user.get("role")
if role == "Administrador":
    pages = all_pages
elif role == "Técnico":
    pages = {
        "Gestão": all_pages["Gestão"],
        "Pós-venda": all_pages["Pós-venda"],
        "Engenharia": all_pages["Engenharia"],
    }
elif role == "Financeiro":
    pages = {
        "Gestão": all_pages["Gestão"],
        "Financeiro": [
            all_pages["Pós-venda"][0],  # Leituras e faturas
            all_pages["Pós-venda"][1],  # Auditoria de faturas
            all_pages["Pós-venda"][2],  # Compensação
            all_pages["Pós-venda"][-1],  # Relatórios
            all_pages["Comercial"][2],  # Caixa
            all_pages["Comercial"][4],  # Contratos
        ],
    }
else:  # Comercial
    pages = {
        "Gestão": all_pages["Gestão"],
        "Comercial": all_pages["Comercial"][:-1],
    }

with st.sidebar:
    st.image(active_logo, width="stretch")
    st.markdown(f"### {active_app_name}")
    st.caption("Operação, pós-venda e engenharia solar · v2.1")
    st.caption("Banco em nuvem" if using_postgres() else "Banco local")
    st.divider()

page = st.navigation(pages, position="sidebar")

with st.sidebar:
    render_user_sidebar(authenticated)

st.title(page.title, icon=page.icon)
page.run()
