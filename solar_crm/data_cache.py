from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from solar_crm.db import available_months, dashboard_metrics, query_df


@st.cache_data(ttl="30s", max_entries=24, show_spinner=False)
def dashboard_months(database_identity: str) -> list[str]:
    return available_months()


@st.cache_data(ttl="30s", max_entries=24, show_spinner=False)
def dashboard_summary(reference_month: str, database_identity: str) -> dict[str, Any]:
    return dashboard_metrics(reference_month)


@st.cache_data(ttl="30s", max_entries=96, show_spinner=False)
def dashboard_frame(sql: str, params: tuple[Any, ...], database_identity: str) -> pd.DataFrame:
    return query_df(sql, params)

