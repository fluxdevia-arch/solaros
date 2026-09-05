import streamlit as st

from solar_crm.auth import render_user_sidebar, require_login
from solar_crm.branding import APP_LOGO, APP_NAME
from solar_crm.config import seed_demo_data
from solar_crm.db import SCHEMA_VERSION, database_cache_key, init_db, using_postgres

st.set_page_config(
    page_title=f"{APP_NAME} · Gestão solar",
    page_icon=":material/solar_power:",
    layout="wide",
    initial_sidebar_state="auto",
)
st.logo(str(APP_LOGO), size="large")

field_order_mode = bool(str(st.query_params.get("os") or "").strip())
field_inspection_mode = bool(str(st.query_params.get("inspection") or "").strip())
field_mode = field_order_mode or field_inspection_mode
authenticated = False if field_mode else require_login()


@st.cache_resource(show_spinner=False)
def prepare_database(schema_version: int, seed: bool, database_identity: str) -> int:
    """Initialize tables once per process and again whenever the schema changes."""
    init_db(seed=seed)
    return schema_version


prepare_database(SCHEMA_VERSION, seed_demo_data(), database_cache_key())

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

pages = {
    "Gestão": [
        st.Page("app_pages/dashboard.py", title="Visão geral", icon=":material/space_dashboard:"),
        st.Page("app_pages/clients.py", title="Clientes e contratos", icon=":material/groups:"),
        st.Page("app_pages/plants.py", title="Usinas", icon=":material/solar_power:"),
    ],
    "Pós-venda": [
        st.Page("app_pages/readings.py", title="Leituras e faturas", icon=":material/bolt:"),
        st.Page("app_pages/integrations.py", title="Integrações", icon=":material/api:"),
        st.Page("app_pages/operations.py", title="Operação e agenda", icon=":material/build:"),
        st.Page("app_pages/service_orders.py", title="Ordens de serviço", icon=":material/assignment:"),
        st.Page("app_pages/inspections.py", title="Vistorias", icon=":material/fact_check:"),
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

page = st.navigation(pages, position="sidebar")

with st.sidebar:
    st.markdown(f"### {APP_NAME}")
    st.caption("Operação, pós-venda e engenharia solar · v2.1")
    st.caption("Banco em nuvem" if using_postgres() else "Banco local")
    st.divider()
    render_user_sidebar(authenticated)

st.title(page.title, icon=page.icon)
page.run()
