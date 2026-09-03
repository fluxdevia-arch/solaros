from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from solar_crm.calculations import money, number_br


MONTHS_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def month_label(value: str) -> str:
    try:
        parsed = datetime.strptime(value[:10], "%Y-%m-%d")
        return f"{MONTHS_PT[parsed.month]} de {parsed.year}"
    except (TypeError, ValueError):
        return value


def date_br(value: str | date | None) -> str:
    if not value:
        return "-"
    try:
        if isinstance(value, date):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value)).date()
        return parsed.strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def page_intro(text: str) -> None:
    st.caption(text)


def empty_state(title: str, text: str, icon: str = ":material/inbox:") -> None:
    with st.container(border=True, horizontal_alignment="center"):
        st.subheader(title, icon=icon)
        st.caption(text)


def status_badge(status: str) -> str:
    color = {
        "Ativo": "green", "Operando": "green", "Pago": "green", "Concluída": "green",
        "Resolvido": "green", "Pendente": "orange", "Em andamento": "blue",
        "Em atendimento": "blue", "Atenção": "orange", "Atrasada": "red",
        "Crítica": "red", "Alta": "orange", "Inativo": "gray", "Desativada": "gray",
        "Cancelada": "gray", "Aberto": "red",
    }.get(status, "gray")
    return f":{color}-badge[{status}]"


def show_flash() -> None:
    message = st.session_state.pop("flash_message", None)
    if message:
        kind, text = message
        getattr(st, kind)(text)


def flash(text: str, kind: str = "success") -> None:
    st.session_state["flash_message"] = (kind, text)


def metric_row(items: list[dict]) -> None:
    with st.container(horizontal=True):
        for item in items:
            st.metric(
                item["label"],
                item["value"],
                delta=item.get("delta"),
                delta_color=item.get("delta_color", "normal"),
                border=True,
                chart_data=item.get("chart_data"),
                chart_type=item.get("chart_type", "line"),
            )


def csv_download(df: pd.DataFrame, filename: str, label: str = "Exportar CSV") -> None:
    st.download_button(
        label,
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name=filename,
        mime="text/csv",
        icon=":material/download:",
    )


def client_options(rows: list[dict]) -> dict[str, int]:
    return {row["name"]: int(row["id"]) for row in rows}


def plant_options(rows: list[dict]) -> dict[str, int]:
    return {f"{row['name']} · {row.get('client_name', '')}": int(row["id"]) for row in rows}


def format_dashboard_value(kind: str, value: float) -> str:
    if kind == "money":
        return money(value)
    if kind == "energy":
        return f"{number_br(value / 1000, 1)} MWh"
    return number_br(value)
