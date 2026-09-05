from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from solar_crm.db import available_months, dashboard_metrics, query_df


@st.cache_data(ttl="30s", max_entries=24, show_spinner=False)
def dashboard_months(database_identity: str, schema_version: int) -> list[str]:
    return available_months()


@st.cache_data(ttl="30s", max_entries=24, show_spinner=False)
def dashboard_summary(
    reference_month: str,
    database_identity: str,
    schema_version: int,
) -> dict[str, Any]:
    return dashboard_metrics(reference_month)


@st.cache_data(ttl="30s", max_entries=96, show_spinner=False)
def dashboard_frame(
    sql: str,
    params: tuple[Any, ...],
    database_identity: str,
    schema_version: int,
) -> pd.DataFrame:
    return query_df(sql, params)


def complete_dashboard_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Keep the dashboard safe while an older cached payload is being replaced."""
    defaults = {
        "active_clients": 0,
        "plants": 0,
        "kwp": 0,
        "generation": 0,
        "savings": 0,
        "availability": 0,
        "overdue": 0,
        "open_tasks": 0,
        "mrr": 0,
        "receivable": 0,
    }
    if metrics:
        defaults.update(metrics)
    return defaults


def clear_dashboard_caches() -> None:
    """Force the next dashboard render to read fresh database values."""
    dashboard_months.clear()
    dashboard_summary.clear()
    dashboard_frame.clear()
