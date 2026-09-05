from __future__ import annotations

import streamlit as st

from solar_crm.branding import APP_LOGO, APP_NAME
from solar_crm.config import allowed_emails, as_bool, database_url, setting


def authentication_configured() -> bool:
    try:
        auth = st.secrets.get("auth", {})
    except (FileNotFoundError, KeyError, RuntimeError):
        return False
    required = ("redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url")
    return all(str(auth.get(key, "")).strip() for key in required)


def authentication_required() -> bool:
    configured = setting("SOLAROS_REQUIRE_AUTH", default=None)
    return as_bool(configured, default=bool(database_url()))


def require_login() -> bool:
    """Render the secure login boundary. Returns False only in local development mode."""
    configured = authentication_configured()
    if not configured:
        if authentication_required():
            st.error("A autenticação do SolarOS ainda não foi configurada.", icon=":material/lock:")
            st.info(
                "Cadastre a seção [auth] nos segredos da hospedagem antes de liberar o sistema."
            )
            st.stop()
        return False

    if not st.user.is_logged_in:
        with st.container(horizontal_alignment="center"):
            st.image(str(APP_LOGO), width=380)
            st.title(APP_NAME, text_alignment="center")
            st.subheader("Gestão profissional de energia solar", text_alignment="center")
        with st.container(border=True):
            st.markdown("#### Acesso restrito")
            st.write("Entre com seu e-mail e sua senha para acessar os dados da empresa.")
            if st.button(
                f"Entrar no {APP_NAME}",
                type="primary",
                icon=":material/login:",
                width="stretch",
            ):
                st.login()
        st.caption("As credenciais são protegidas pelo provedor de identidade e não ficam salvas no SolarOS.")
        st.stop()

    email = str(getattr(st.user, "email", "") or "").strip().lower()
    permitted = allowed_emails()
    if permitted and email not in permitted:
        st.error("Este usuário não tem permissão para acessar o SolarOS.", icon=":material/block:")
        st.write(f"Conta autenticada: {email or 'e-mail não informado'}")
        if st.button("Sair", icon=":material/logout:"):
            st.logout()
        st.stop()
    return True


def render_user_sidebar(authenticated: bool) -> None:
    if not authenticated:
        st.caption("Modo local sem autenticação")
        return
    name = str(getattr(st.user, "name", "") or "Usuário")
    email = str(getattr(st.user, "email", "") or "")
    st.caption(f"Conectado como **{name}**")
    if email:
        st.caption(email)
    if st.button("Sair", icon=":material/logout:", width="stretch"):
        st.logout()
