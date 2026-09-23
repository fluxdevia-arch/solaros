from __future__ import annotations

import streamlit as st

from solar_crm.branding import APP_LOGO, APP_NAME
from solar_crm.config import allowed_emails, as_bool, database_url, setting
from solar_crm.db import execute, now_iso, query, query_one


ROLES = ["Administrador", "Técnico", "Financeiro", "Comercial"]

ROLE_SECTIONS = {
    "Administrador": {"Gestão", "Pós-venda", "Engenharia", "Comercial"},
    "Técnico": {"Gestão", "Pós-venda", "Engenharia"},
    "Financeiro": {"Gestão", "Financeiro"},
    "Comercial": {"Gestão", "Comercial"},
}


def authenticated_identity() -> tuple[str, str]:
    if not authentication_configured() or not st.user.is_logged_in:
        return "local@gridengenharia.app", "Administrador local"
    email = str(getattr(st.user, "email", "") or "").strip().lower()
    name = str(getattr(st.user, "name", "") or email).strip()
    return email, name


def current_app_user() -> dict:
    """Resolve the verified OIDC identity to an application role."""
    email, name = authenticated_identity()
    if email == "local@gridengenharia.app":
        return {"email": email, "name": name, "role": "Administrador", "active": 1}
    user = query_one("SELECT * FROM app_users WHERE email=?", (email,))
    if user:
        if name and name != (user.get("name") or ""):
            execute("UPDATE app_users SET name=?, updated_at=? WHERE id=?", (name, now_iso(), user["id"]))
            user["name"] = name
        return user
    total = query_one("SELECT COUNT(*) AS value FROM app_users")
    # The first verified account safely bootstraps administration. Every later
    # account must be invited by an administrator before it can enter.
    if int(total["value"] or 0) == 0:
        execute(
            "INSERT INTO app_users (email, name, role, active, updated_at) VALUES (?, ?, 'Administrador', 1, ?)",
            (email, name, now_iso()),
        )
        return query_one("SELECT * FROM app_users WHERE email=?", (email,))
    return {"email": email, "name": name, "role": "Sem acesso", "active": 0}


def list_app_users() -> list[dict]:
    return query("SELECT * FROM app_users ORDER BY active DESC, role, name, email")


def save_app_user(email: str, name: str, role: str, active: bool = True) -> int:
    normalized = email.strip().lower()
    if "@" not in normalized:
        raise ValueError("Informe um e-mail válido.")
    if role not in ROLES:
        raise ValueError("Perfil de acesso inválido.")
    existing = query_one("SELECT id FROM app_users WHERE email=?", (normalized,))
    if existing:
        execute(
            "UPDATE app_users SET name=?, role=?, active=?, updated_at=? WHERE id=?",
            (name.strip(), role, int(active), now_iso(), existing["id"]),
        )
        return int(existing["id"])
    return execute(
        "INSERT INTO app_users (email, name, role, active, updated_at) VALUES (?, ?, ?, ?, ?)",
        (normalized, name.strip(), role, int(active), now_iso()),
    )


def role_allows(section: str, user: dict | None = None) -> bool:
    resolved = user or st.session_state.get("app_user") or current_app_user()
    return bool(resolved.get("active")) and section in ROLE_SECTIONS.get(resolved.get("role"), set())


def require_role(*roles: str) -> dict:
    user = st.session_state.get("app_user") or current_app_user()
    if not user.get("active") or user.get("role") not in roles:
        st.error("Seu perfil não tem permissão para acessar esta função.", icon=":material/block:")
        st.stop()
    return user


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


def require_login(app_name: str = APP_NAME, app_logo=APP_LOGO) -> bool:
    """Render the secure login boundary. Returns False only in local development mode."""
    configured = authentication_configured()
    if not configured:
        if authentication_required():
            st.error(f"A autenticação do {app_name} ainda não foi configurada.", icon=":material/lock:")
            st.info(
                "Cadastre a seção [auth] nos segredos da hospedagem antes de liberar o sistema."
            )
            st.stop()
        return False

    if not st.user.is_logged_in:
        with st.container(horizontal_alignment="center"):
            st.image(app_logo, width=380)
            st.title(app_name, text_alignment="center")
            st.subheader("Gestão profissional de energia solar", text_alignment="center")
        with st.container(border=True):
            st.markdown("#### Acesso restrito")
            st.write("Entre com seu e-mail e sua senha para acessar os dados da empresa.")
            if st.button(
                f"Entrar no {app_name}",
                type="primary",
                icon=":material/login:",
                width="stretch",
            ):
                st.login()
        st.caption("As credenciais são protegidas pelo provedor de identidade e não ficam salvas no sistema.")
        st.stop()

    email = str(getattr(st.user, "email", "") or "").strip().lower()
    permitted = allowed_emails()
    invited = query_one("SELECT active FROM app_users WHERE email=?", (email,)) if email else None
    if permitted and email not in permitted and not (invited and invited.get("active")):
        st.error(f"Este usuário não tem permissão para acessar o {app_name}.", icon=":material/block:")
        st.write(f"Conta autenticada: {email or 'e-mail não informado'}")
        if st.button("Sair", icon=":material/logout:"):
            st.logout()
        st.stop()
    return True


def render_user_sidebar(authenticated: bool) -> None:
    if not authenticated:
        st.caption("Modo local sem autenticação")
        return
    user = st.session_state.get("app_user") or current_app_user()
    name = user.get("name") or "Usuário"
    email = user.get("email") or ""
    st.caption(f"Conectado como **{name}**")
    if email:
        st.caption(email)
    st.caption(f"Perfil: **{user.get('role') or '-'}**")
    if st.button("Sair", icon=":material/logout:", width="stretch"):
        st.logout()
