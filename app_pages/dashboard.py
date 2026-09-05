from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from solar_crm.calculations import money, number_br, percent
from solar_crm.data_cache import (
    clear_dashboard_caches,
    complete_dashboard_metrics,
    dashboard_frame,
    dashboard_months,
    dashboard_summary,
)
from solar_crm.db import SCHEMA_VERSION, database_cache_key
from solar_crm.ui import date_br, month_label, page_intro, status_badge

page_intro("Indicadores financeiros, desempenho energético e prioridades operacionais em uma única visão.")

with st.container(horizontal=True, horizontal_alignment="right"):
    st.button(
        "Atualizar dados",
        icon=":material/refresh:",
        key="dashboard_refresh",
        on_click=clear_dashboard_caches,
    )

db_identity = database_cache_key()
months = dashboard_months(db_identity, SCHEMA_VERSION)
reference_month = st.selectbox(
    "Mês de referência",
    months,
    format_func=month_label,
    key="dashboard_month",
) if months else date.today().replace(day=1).isoformat()

metrics = complete_dashboard_metrics(
    dashboard_summary(reference_month, db_identity, SCHEMA_VERSION)
)

with st.container(horizontal=True):
    st.metric("Clientes ativos", int(metrics["active_clients"]), border=True)
    st.metric("Usinas monitoradas", int(metrics["plants"]), border=True)
    st.metric("Potência instalada", f"{number_br(metrics['kwp'], 1)} kWp", border=True)
    st.metric("Receita recorrente", money(metrics["mrr"]), border=True)
    st.metric("A receber no mês", money(metrics["receivable"]), border=True)

with st.container(horizontal=True):
    st.metric("Geração no mês", f"{number_br(metrics['generation'] / 1000, 1)} MWh", border=True)
    st.metric("Economia do cliente", money(metrics["savings"]), border=True)
    st.metric("Disponibilidade média", percent(metrics["availability"]), border=True)
    st.metric(
        "Tarefas atrasadas",
        int(metrics["overdue"]),
        delta=f"{int(metrics['open_tasks'])} em aberto",
        delta_color="inverse" if metrics["overdue"] else "off",
        border=True,
    )

trend = dashboard_frame(
    """SELECT r.reference_month AS month,
              SUM(r.generation_kwh)/1000.0 AS generation_mwh,
              SUM(r.reference_amount-r.billed_amount) AS savings
       FROM readings r GROUP BY r.reference_month ORDER BY r.reference_month""",
    (),
    db_identity,
    SCHEMA_VERSION,
)
if not trend.empty:
    trend["month"] = pd.to_datetime(trend["month"])

performance = dashboard_frame(
    """SELECT p.name AS plant, c.name AS client,
              COALESCE(r.generation_kwh,0) AS generation,
              p.expected_monthly_kwh AS expected,
              CASE WHEN p.expected_monthly_kwh>0 THEN COALESCE(r.generation_kwh,0)/p.expected_monthly_kwh*100 ELSE 0 END AS performance,
              COALESCE(r.availability_pct,0) AS availability,
              p.status
       FROM plants p JOIN clients c ON c.id=p.client_id
       LEFT JOIN readings r ON r.plant_id=p.id AND r.reference_month=?
       ORDER BY performance ASC""",
    (reference_month,),
    db_identity,
    SCHEMA_VERSION,
)

left, right = st.columns([1.55, 1])
with left:
    with st.container(border=True):
        st.subheader("Geração e economia", icon=":material/query_stats:")
        if not trend.empty:
            generation_chart = alt.Chart(trend).mark_area(opacity=0.2, line=True).encode(
                x=alt.X("month:T", title="Mês", axis=alt.Axis(format="%b/%y")),
                y=alt.Y("generation_mwh:Q", title="Geração (MWh)"),
                tooltip=[alt.Tooltip("month:T", title="Mês", format="%m/%Y"), alt.Tooltip("generation_mwh:Q", title="Geração", format=".1f")],
            )
            st.altair_chart(generation_chart)
            st.caption(f"Economia consolidada em {month_label(reference_month)}: {money(metrics['savings'])}")
        else:
            st.caption("Cadastre leituras mensais para visualizar a evolução.")

with right:
    with st.container(border=True):
        st.subheader("Saúde das usinas", icon=":material/health_metrics:")
        if not performance.empty:
            normal = int((performance["performance"] >= 90).sum())
            attention = int(((performance["performance"] < 90) & (performance["performance"] >= 75)).sum())
            critical = int((performance["performance"] < 75).sum())
            st.markdown(f":green-badge[{normal} normais] :orange-badge[{attention} atenção] :red-badge[{critical} críticas]")
            health = performance[["plant", "performance"]].copy()
            health["health"] = pd.cut(
                health["performance"],
                bins=[-float("inf"), 75, 90, float("inf")],
                labels=["Crítica", "Atenção", "Normal"],
                right=False,
            )
            chart = alt.Chart(health).mark_bar(cornerRadiusEnd=4).encode(
                x=alt.X("performance:Q", title="Desempenho (%)", scale=alt.Scale(domain=[0, max(110, float(health['performance'].max()) + 5)])),
                y=alt.Y("plant:N", title=None, sort="x"),
                color=alt.Color(
                    "health:N",
                    title=None,
                    scale=alt.Scale(
                        domain=["Normal", "Atenção", "Crítica"],
                        range=["#0B7A53", "#E3A72F", "#C43D3D"],
                    ),
                    legend=None,
                ),
                tooltip=[alt.Tooltip("plant:N", title="Usina"), alt.Tooltip("performance:Q", title="Desempenho", format=".1f")],
            )
            st.altair_chart(chart)
        else:
            st.caption("Sem dados de desempenho para o mês.")

st.subheader("Prioridades da equipe", icon=":material/priority_high:")
today = date.today().isoformat()
tasks = dashboard_frame(
    """SELECT t.id, t.due_date, t.title, t.priority, t.status, t.assignee,
              c.name AS client, COALESCE(p.name,'Geral') AS plant
       FROM tasks t JOIN clients c ON c.id=t.client_id
       LEFT JOIN plants p ON p.id=t.plant_id
       WHERE t.status NOT IN ('Concluída','Cancelada')
       ORDER BY CASE t.priority WHEN 'Crítica' THEN 1 WHEN 'Alta' THEN 2 WHEN 'Média' THEN 3 ELSE 4 END,
                t.due_date LIMIT 10""",
    (),
    db_identity,
    SCHEMA_VERSION,
)
if not tasks.empty:
    tasks["Prazo"] = tasks["due_date"].map(date_br)
    tasks["Status"] = tasks.apply(lambda row: "Atrasada" if row["due_date"] < today else row["status"], axis=1)
    show = tasks.rename(columns={"title": "Atividade", "priority": "Prioridade", "assignee": "Responsável", "client": "Cliente", "plant": "Usina"})
    st.dataframe(
        show[["Prazo", "Atividade", "Cliente", "Usina", "Prioridade", "Status", "Responsável"]],
        hide_index=True,
        column_config={
            "Atividade": st.column_config.TextColumn(pinned=True),
            "Prioridade": st.column_config.TextColumn(width="small"),
            "Status": st.column_config.TextColumn(width="small"),
        },
    )
else:
    st.success("Nenhuma pendência operacional.", icon=":material/check_circle:")

st.caption(f"Painel atualizado com dados registrados até {date_br(date.today())}.")
