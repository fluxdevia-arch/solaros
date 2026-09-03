from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote


def _streamlit_secret(section: str, key: str) -> Any | None:
    """Read a nested Streamlit secret without making CLI scripts depend on Streamlit."""
    try:
        import streamlit as st

        values = st.secrets.get(section, {})
        return values.get(key) if hasattr(values, "get") else None
    except (FileNotFoundError, KeyError, RuntimeError):
        return None


def setting(name: str, *, section: str = "solaros", default: Any = None) -> Any:
    """Return an environment override or a value from Streamlit secrets."""
    value = os.getenv(name)
    if value not in (None, ""):
        return value
    secret_value = _streamlit_secret(section, name.lower())
    return default if secret_value in (None, "") else secret_value


def database_url() -> str:
    environment_value = os.getenv("DATABASE_URL", "").strip()
    if environment_value:
        return environment_value
    configured_url = str(_streamlit_secret("database", "url") or "").strip()
    if configured_url:
        return configured_url

    host = str(_streamlit_secret("database", "host") or "").strip()
    user = str(_streamlit_secret("database", "user") or "").strip()
    password = str(_streamlit_secret("database", "password") or "")
    name = str(_streamlit_secret("database", "name") or "postgres").strip()
    port = str(_streamlit_secret("database", "port") or "5432").strip()
    sslmode = str(_streamlit_secret("database", "sslmode") or "require").strip()
    if not (host and user and password):
        return ""

    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@"
        f"{host}:{port}/{quote(name, safe='')}?sslmode={quote(sslmode, safe='')}"
    )


def encryption_key() -> str:
    return str(setting("SOLAROS_ENCRYPTION_KEY", default="") or "").strip()


def allowed_emails() -> set[str]:
    configured = setting("SOLAROS_ALLOWED_EMAILS", default=[])
    if isinstance(configured, str):
        items = configured.split(",")
    else:
        items = configured or []
    return {str(item).strip().lower() for item in items if str(item).strip()}


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "sim", "on"}


def seed_demo_data() -> bool:
    # Local SQLite keeps the demonstration data. A hosted database starts clean.
    return as_bool(setting("SOLAROS_SEED_DEMO", default=None), default=not bool(database_url()))
