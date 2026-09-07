from __future__ import annotations

import json
import re
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

from solar_crm.calculations import number_br
from solar_crm.document_cache import inverter_curve_pdf
from solar_crm.db import query
from solar_crm.equipment_analysis import (
    AUTH_TYPES,
    EQUIPMENT_PROVIDERS,
    NORMALIZED_REST,
    EquipmentAnalysisError,
    analyze_string_samples,
    available_equipment_days,
    create_equipment_integration,
    equipment_profile,
    load_equipment_alarms,
    load_string_samples,
    sync_equipment_integration,
)
from solar_crm.inverter_curve import (
    FIELD_LABELS,
    CurveAnalysisError,
    analyze_inverter_curve,
    load_curve_history,
    save_curve_analysis,
    suggest_column_mapping,
    workbook_preview,
)
from solar_crm.ui import csv_download, empty_state, flash, page_intro, render_delete_control, show_flash, status_badge


@st.cache_data(ttl="1h", max_entries=24, show_spinner=False)
def _cached_curve_analysis(
    file_bytes: bytes,
    filename: str,
    sheet_name: str,
    mapping_json: str,
    nominal_power_kw: float,
    nominal_grid_voltage_v: float,
):
    return analyze_inverter_curve(
        file_bytes,
        filename,
        sheet_name=sheet_name,
        column_mapping=json.loads(mapping_json),
        nominal_power_kw=nominal_power_kw,
        nominal_grid_voltage_v=nominal_grid_voltage_v,
    )


page_intro(
    "Analise arquivos Excel exportados pelo inversor ou compare strings e alarmes recebidos por API."
)
show_flash()

plants = query(
    """SELECT p.id, p.name, p.inverter, p.installed_kwp, c.name AS client_name
       FROM plants p JOIN clients c ON c.id=p.client_id
       WHERE p.status!='Desativada' ORDER BY c.name, p.name"""
)
if not plants:
    empty_state(
        "Cadastre uma usina primeiro",
        "A análise precisa de uma usina para vincular inversores, strings e alarmes.",
        ":material/solar_power:",
    )
    st.stop()

plant_map = {f"{row['name']} · {row['client_name']}": int(row["id"]) for row in plants}
with st.container(horizontal=True, vertical_alignment="bottom"):
    selected_label = st.selectbox("Usina", list(plant_map), key="equipment_plant")
    plant_id = plant_map[selected_label]
    selected_plant = next(row for row in plants if int(row["id"]) == plant_id)
    available_days = available_equipment_days(plant_id)
    default_day = available_days[0] if available_days else date.today()
    reading_day = st.date_input("Dia analisado", value=default_day, key="equipment_day")

samples = load_string_samples(plant_id, reading_day)
diagnostics = analyze_string_samples(samples)
open_alarms = load_equipment_alarms(plant_id, only_open=True)
sources = query(
    """SELECT id, name, provider, credential_hint, device_sn, status, last_sync_at,
              last_sync_status, last_error
       FROM equipment_integrations WHERE plant_id=? ORDER BY name""",
    (plant_id,),
)

critical_count = sum(item.status == "Crítica" for item in diagnostics)
attention_count = sum(item.status in {"Crítica", "Degradada", "Atenção"} for item in diagnostics)
healthy_count = sum(item.status == "Saudável" for item in diagnostics)
loss_kwh = sum(item.loss_kwh for item in diagnostics)
inverter_count = len({item.inverter_name for item in diagnostics})

with st.container(horizontal=True):
    st.metric("Inversores", inverter_count or len(sources), border=True)
    st.metric(
        "Strings saudáveis",
        f"{healthy_count}/{len(diagnostics)}" if diagnostics else "Sem dados",
        border=True,
    )
    st.metric(
        "Strings com desvio",
        attention_count,
        delta=f"{critical_count} crítica(s)" if critical_count else None,
        delta_color="inverse",
        border=True,
    )
    st.metric("Alarmes ativos", len(open_alarms), border=True)
    st.metric("Perda estimada no dia", f"{number_br(loss_kwh, 1)} kWh", border=True)

overview_tab, excel_tab, strings_tab, alarms_tab, api_tab = st.tabs(
    [
        ":material/monitoring: Visão geral",
        ":material/upload_file: Analisar Excel",
        ":material/electric_bolt: Diagnóstico de strings",
        ":material/report_problem: Falhas e alarmes",
        ":material/api: Fontes de API",
    ]
)

with overview_tab:
    if not diagnostics:
        empty_state(
            "Ainda não há telemetria de strings",
            "Configure uma fonte de API nesta página e sincronize um dia com dados disponíveis.",
            ":material/cable:",
        )
    else:
        if critical_count:
            st.error(
                f"{critical_count} string(s) exigem verificação prioritária nesta usina.",
                icon=":material/error:",
            )
        elif attention_count:
            st.warning(
                f"{attention_count} string(s) apresentam corrente abaixo dos pares do mesmo MPPT.",
                icon=":material/warning:",
            )
        else:
            st.success("Todas as strings monitoradas estão dentro da faixa esperada.", icon=":material/check_circle:")

        summary_left, summary_right = st.columns([1, 2])
        with summary_left.container(border=True, height="stretch"):
            st.subheader("Saúde das strings", icon=":material/vital_signs:")
            status_order = ["Saudável", "Atenção", "Degradada", "Crítica"]
            status_df = pd.DataFrame(
                {
                    "Condição": status_order,
                    "Strings": [sum(item.status == status for item in diagnostics) for status in status_order],
                }
            )
            status_chart = (
                alt.Chart(status_df)
                .mark_bar(cornerRadiusEnd=4)
                .encode(
                    x=alt.X("Strings:Q", title=None, axis=alt.Axis(tickMinStep=1)),
                    y=alt.Y("Condição:N", sort=status_order, title=None),
                    color=alt.Color(
                        "Condição:N",
                        scale=alt.Scale(
                            domain=status_order,
                            range=["#248a5a", "#c28a2c", "#d35d32", "#b73a43"],
                        ),
                        legend=None,
                    ),
                    tooltip=["Condição", "Strings"],
                )
                .properties(height=210)
            )
            st.altair_chart(status_chart)
        with summary_right.container(border=True, height="stretch"):
            st.subheader("Prioridades técnicas", icon=":material/priority_high:")
            diagnostic_df = pd.DataFrame(
                [
                    {
                        "Condição": item.status,
                        "Inversor": item.inverter_name,
                        "MPPT": item.mppt,
                        "String": item.string_name,
                        "Saúde": item.score / 100,
                        "I / mediana": item.current_ratio,
                        "Perda estimada": item.loss_kwh,
                        "Causa provável": item.probable_cause,
                    }
                    for item in diagnostics
                ]
            )
            st.dataframe(
                diagnostic_df,
                hide_index=True,
                column_config={
                    "Saúde": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                    "I / mediana": st.column_config.NumberColumn(format="%.2fx"),
                    "Perda estimada": st.column_config.NumberColumn(format="%.2f kWh"),
                },
            )
        if samples:
            last_sample = max(str(row["sample_at"]) for row in samples)
            st.caption(f"Última amostra do dia: {datetime.fromisoformat(last_sample).strftime('%d/%m/%Y às %H:%M')}.")

with strings_tab:
    if diagnostics:
        selector_left, selector_middle, selector_right = st.columns(3)
        inverter_names = sorted({item.inverter_name for item in diagnostics})
        with selector_left:
            selected_inverter = st.selectbox("Inversor", inverter_names, key="diagnostic_inverter")
        mppts = sorted({item.mppt for item in diagnostics if item.inverter_name == selected_inverter})
        with selector_middle:
            selected_mppt = st.selectbox("MPPT", mppts, key="diagnostic_mppt")
        candidates = [
            item
            for item in diagnostics
            if item.inverter_name == selected_inverter and item.mppt == selected_mppt
        ]
        with selector_right:
            selected_string = st.selectbox(
                "String",
                [item.string_name for item in candidates],
                key="diagnostic_string",
            )
        diagnostic = next(item for item in candidates if item.string_name == selected_string)

        badge_area = st.container(horizontal=True, vertical_alignment="center")
        badge_area.subheader(f"{diagnostic.string_name} · {diagnostic.mppt}")
        badge_area.markdown(status_badge(diagnostic.status))

        with st.container(horizontal=True):
            st.metric(
                "Corrente mais recente",
                f"{number_br(diagnostic.current_a, 2)} A",
                delta=f"{number_br(diagnostic.current_ratio, 2)}x da mediana",
                delta_color="off",
                border=True,
            )
            st.metric("Tensão no MPPT", f"{number_br(diagnostic.voltage_v, 0)} V", border=True)
            st.metric("Perda estimada", f"{number_br(diagnostic.loss_kwh, 1)} kWh", border=True)
            st.metric("Padrão do déficit", diagnostic.pattern, border=True)
            st.metric(
                "Produção estimada",
                f"{number_br(diagnostic.energy_kwh, 1)} kWh",
                delta=f"par: {number_br(diagnostic.peer_energy_kwh, 1)} kWh",
                delta_color="off",
                border=True,
            )

        selected_rows = [
            row
            for row in samples
            if row["inverter_name"] == selected_inverter and row["mppt"] == selected_mppt
        ]
        trend_records = []
        for timestamp in sorted({str(row["sample_at"]) for row in selected_rows}):
            time_rows = [row for row in selected_rows if str(row["sample_at"]) == timestamp]
            currents = [float(row["current_a"] or 0) for row in time_rows if float(row["current_a"] or 0) > 0.15]
            peer = float(pd.Series(currents).median()) if currents else 0
            own = next((float(row["current_a"] or 0) for row in time_rows if row["string_name"] == selected_string), 0)
            trend_records.extend(
                [
                    {"Horário": timestamp, "Corrente": own, "Série": selected_string},
                    {"Horário": timestamp, "Corrente": peer, "Série": "Mediana do MPPT"},
                ]
            )
        trend_df = pd.DataFrame(trend_records)
        trend_df["Horário"] = pd.to_datetime(trend_df["Horário"])
        trend_chart = (
            alt.Chart(trend_df)
            .mark_line(strokeWidth=3)
            .encode(
                x=alt.X("Horário:T", title=None, axis=alt.Axis(format="%Hh")),
                y=alt.Y("Corrente:Q", title="Corrente (A)"),
                color=alt.Color(
                    "Série:N",
                    scale=alt.Scale(domain=[selected_string, "Mediana do MPPT"], range=["#d35d32", "#697386"]),
                    legend=alt.Legend(orient="top"),
                ),
                strokeDash=alt.StrokeDash(
                    "Série:N",
                    scale=alt.Scale(domain=[selected_string, "Mediana do MPPT"], range=[[1, 0], [6, 5]]),
                    legend=None,
                ),
                tooltip=[alt.Tooltip("Horário:T", format="%H:%M"), "Série", alt.Tooltip("Corrente:Q", format=".2f")],
            )
            .properties(height=330, title=f"Corrente versus mediana do MPPT · {reading_day.strftime('%d/%m/%Y')}")
            .interactive(bind_y=False)
        )
        st.altair_chart(trend_chart)

        deficit_records = []
        for timestamp in sorted({str(row["sample_at"]) for row in selected_rows}):
            time_rows = [row for row in selected_rows if str(row["sample_at"]) == timestamp]
            currents = [float(row["current_a"] or 0) for row in time_rows if float(row["current_a"] or 0) > 0.15]
            peer = float(pd.Series(currents).median()) if currents else 0
            own = next((float(row["current_a"] or 0) for row in time_rows if row["string_name"] == selected_string), 0)
            deficit_records.append(
                {
                    "Hora": datetime.fromisoformat(timestamp).strftime("%Hh"),
                    "Déficit": max(1 - own / peer, 0) if peer > 0.5 else 0,
                }
            )
        deficit_chart = (
            alt.Chart(pd.DataFrame(deficit_records))
            .mark_bar(cornerRadius=2)
            .encode(
                x=alt.X("Hora:N", title="Padrão horário do déficit", sort=None),
                y=alt.Y("Déficit:Q", title=None, axis=None, scale=alt.Scale(domain=[0, 1])),
                color=alt.Color(
                    "Déficit:Q",
                    scale=alt.Scale(domain=[0, 0.5], range=["#e7ebef", "#b73a43"]),
                    legend=None,
                ),
                tooltip=["Hora", alt.Tooltip("Déficit:Q", format=".0%")],
            )
            .properties(height=90)
        )
        st.altair_chart(deficit_chart)

        with st.container(border=True):
            st.subheader("Causa provável", icon=":material/troubleshoot:")
            cause_left, cause_right = st.columns([3, 1], vertical_alignment="center")
            cause_left.markdown(f"**{diagnostic.probable_cause}**")
            cause_left.caption(
                "Classificação baseada na persistência e na janela horária do desvio em relação às strings pares. "
                "Confirme em campo antes de substituir componentes."
            )
            cause_right.metric("Confiança", f"{diagnostic.confidence:.0%}", border=True)
    else:
        empty_state(
            "Sem strings para analisar neste dia",
            "Sincronize a API ou escolha outra data com telemetria disponível.",
            ":material/electric_bolt:",
        )

with excel_tab:
    st.subheader("Curva diária do inversor", icon=":material/upload_file:")
    st.caption(
        "Envie o .xlsx original do portal. A ordem das colunas não importa: o SolarOS reconhece nomes, "
        "unidades, abreviações e qualquer quantidade de MPPTs. O diagnóstico indica evidências e não "
        "substitui o datasheet, a medição em campo ou a avaliação do responsável técnico."
    )
    uploaded_curve = st.file_uploader(
        "Relatório Excel do inversor",
        type=["xlsx"],
        key=f"inverter_curve_file_{plant_id}",
        help="Exporte o relatório diário diretamente do portal, sem reorganizar as colunas.",
    )
    if uploaded_curve is not None:
        file_bytes = uploaded_curve.getvalue()
        try:
            sheet_names, first_preview, default_sheet = workbook_preview(file_bytes)
            selected_sheet = st.selectbox(
                "Planilha com os dados",
                sheet_names,
                index=sheet_names.index(default_sheet),
                key=f"curve_sheet_{plant_id}_{uploaded_curve.name}",
            )
            _, preview, _ = workbook_preview(file_bytes, selected_sheet)
            automatic_mapping = suggest_column_mapping(list(preview.columns))

            with st.expander("Campos identificados e ajuste manual", icon=":material/account_tree:"):
                identified = pd.DataFrame(
                    [
                        {
                            "Dado técnico": FIELD_LABELS.get(field, field.replace("_", " ").upper()),
                            "Coluna do Excel": column,
                        }
                        for field, column in automatic_mapping.items()
                    ]
                )
                if identified.empty:
                    st.warning("Nenhum campo foi identificado automaticamente. Faça o mapeamento abaixo.")
                else:
                    st.dataframe(identified, hide_index=True)
                st.caption("Se algum fabricante usar um título diferente, selecione a coluna correta. Campos opcionais podem ficar em branco.")
                options = ["— Não informado —", *map(str, preview.columns)]
                manual_mapping: dict[str, str] = {}
                core_fields = list(FIELD_LABELS)
                mapping_columns = st.columns(2)
                for index, field in enumerate(core_fields):
                    current = automatic_mapping.get(field)
                    selected = mapping_columns[index % 2].selectbox(
                        FIELD_LABELS[field],
                        options,
                        index=options.index(current) if current in options else 0,
                        key=f"curve_map_{plant_id}_{field}_{uploaded_curve.name}",
                    )
                    if selected != options[0]:
                        manual_mapping[field] = selected
                mppt_count = st.number_input(
                    "Quantidade de MPPTs para mapear manualmente",
                    min_value=0,
                    max_value=20,
                    value=max(
                        [int(field.split("_")[1]) for field in automatic_mapping if field.startswith("mppt_")]
                        or [0]
                    ),
                    step=1,
                    key=f"curve_mppt_count_{plant_id}_{uploaded_curve.name}",
                )
                for mppt_id in range(1, int(mppt_count) + 1):
                    current_field = f"mppt_{mppt_id}_current_a"
                    voltage_field = f"mppt_{mppt_id}_voltage_v"
                    left, right = st.columns(2)
                    current_default = automatic_mapping.get(current_field)
                    voltage_default = automatic_mapping.get(voltage_field)
                    current_selected = left.selectbox(
                        f"MPPT {mppt_id} · corrente (A)",
                        options,
                        index=options.index(current_default) if current_default in options else 0,
                        key=f"curve_map_{plant_id}_{current_field}_{uploaded_curve.name}",
                    )
                    voltage_selected = right.selectbox(
                        f"MPPT {mppt_id} · tensão (V)",
                        options,
                        index=options.index(voltage_default) if voltage_default in options else 0,
                        key=f"curve_map_{plant_id}_{voltage_field}_{uploaded_curve.name}",
                    )
                    if current_selected != options[0]:
                        manual_mapping[current_field] = current_selected
                    if voltage_selected != options[0]:
                        manual_mapping[voltage_field] = voltage_selected

            settings_left, settings_middle, settings_right = st.columns(3)
            inverter_name = settings_left.text_input(
                "Inversor / identificação",
                value=str(selected_plant.get("inverter") or "Inversor principal"),
                key=f"curve_inverter_{plant_id}_{uploaded_curve.name}",
            )
            nominal_power = settings_middle.number_input(
                "Potência nominal do inversor (kW)",
                min_value=0.0,
                value=0.0,
                step=0.5,
                help="Opcional. Melhora a análise de pico e clipping.",
                key=f"curve_nominal_{plant_id}_{uploaded_curve.name}",
            )
            nominal_voltage = settings_right.number_input(
                "Tensão nominal monitorada (V)",
                min_value=100.0,
                max_value=800.0,
                value=220.0,
                step=1.0,
                key=f"curve_voltage_{plant_id}_{uploaded_curve.name}",
            )

            with st.spinner("Lendo curvas e avaliando possíveis anomalias..."):
                mapping_json = json.dumps(manual_mapping, ensure_ascii=False, sort_keys=True)
                curve_result = _cached_curve_analysis(
                    file_bytes,
                    uploaded_curve.name,
                    selected_sheet,
                    mapping_json,
                    float(nominal_power),
                    float(nominal_voltage),
                )
            summary = curve_result["summary"]
            status = summary["health_status"]
            if status == "Crítica":
                st.error("Foram encontrados indícios que exigem verificação prioritária.", icon=":material/error:")
            elif status == "Atenção":
                st.warning("Foram encontrados desvios que merecem conferência técnica.", icon=":material/warning:")
            else:
                st.success("Nenhuma anomalia evidente foi encontrada nos dados disponíveis.", icon=":material/check_circle:")

            with st.container(horizontal=True):
                st.metric("Situação", status, border=True)
                st.metric("Geração do dia", f"{number_br(summary['daily_energy_kwh'], 2)} kWh", border=True)
                st.metric("Pico de potência", f"{number_br(summary['peak_power_kw'], 2)} kW", border=True)
                st.metric("Tempo em operação", f"{number_br(summary['operating_hours'], 1)} h", border=True)
                st.metric("Amostras válidas", summary["sample_count"], border=True)
                st.metric("Achados", summary["issue_count"], border=True)

            curve_data = curve_result["data"]
            power_columns = [column for column in ("active_power_kw", "pv_power_kw") if column in curve_data]
            power_labels = {"active_power_kw": "Potência ativa", "pv_power_kw": "Potência FV"}
            if power_columns:
                power_chart_data = curve_data[["timestamp", *power_columns]].melt(
                    "timestamp", var_name="series", value_name="power_kw"
                )
                power_chart_data["series"] = power_chart_data["series"].map(power_labels)
                power_chart = (
                    alt.Chart(power_chart_data)
                    .mark_line(strokeWidth=2.5)
                    .encode(
                        x=alt.X("timestamp:T", title=None, axis=alt.Axis(format="%H:%M")),
                        y=alt.Y("power_kw:Q", title="Potência (kW)"),
                        color=alt.Color("series:N", title=None, legend=alt.Legend(orient="top")),
                        tooltip=[alt.Tooltip("timestamp:T", title="Horário", format="%H:%M"), "series:N", alt.Tooltip("power_kw:Q", title="kW", format=".2f")],
                    )
                    .properties(height=330, title="Curva de potência do dia")
                    .interactive(bind_y=False)
                )
                st.altair_chart(power_chart)

            mppt_current_columns = [column for column in curve_data if re.match(r"mppt_\d+_current_a", column)]
            mppt_voltage_columns = [column for column in curve_data if re.match(r"mppt_\d+_voltage_v", column)]
            if mppt_current_columns or mppt_voltage_columns:
                chart_left, chart_right = st.columns(2)
                for target, columns, value_name, title, unit in (
                    (chart_left, mppt_current_columns, "current", "Corrente por MPPT", "Corrente (A)"),
                    (chart_right, mppt_voltage_columns, "voltage", "Tensão por MPPT", "Tensão (V)"),
                ):
                    if not columns:
                        continue
                    melted = curve_data[["timestamp", *columns]].melt("timestamp", var_name="mppt", value_name=value_name)
                    melted["mppt"] = melted["mppt"].str.extract(r"mppt_(\d+)")[0].map(lambda value: f"MPPT {value}")
                    chart = (
                        alt.Chart(melted)
                        .mark_line(strokeWidth=2)
                        .encode(
                            x=alt.X("timestamp:T", title=None, axis=alt.Axis(format="%Hh")),
                            y=alt.Y(f"{value_name}:Q", title=unit),
                            color=alt.Color("mppt:N", title=None, legend=alt.Legend(orient="top")),
                            tooltip=[alt.Tooltip("timestamp:T", format="%H:%M"), "mppt:N", alt.Tooltip(f"{value_name}:Q", format=".2f")],
                        )
                        .properties(height=270, title=title)
                    )
                    target.altair_chart(chart)

            with st.expander("Curvas elétricas e térmicas", icon=":material/electric_meter:"):
                auxiliary_groups = [
                    (["daily_energy_kwh"], "Energia acumulada no dia", "Energia (kWh)"),
                    ([column for column in curve_data if column == "grid_voltage_v" or re.match(r"phase_[abc]_voltage_v", column)], "Tensões da rede", "Tensão (V)"),
                    (["frequency_hz"], "Frequência da rede", "Frequência (Hz)"),
                    ([column for column in ("heatsink_temp_c", "internal_temp_c") if column in curve_data], "Temperaturas", "Temperatura (°C)"),
                    (["insulation_kohm"], "Resistência de isolamento", "Isolamento (kΩ)"),
                    (["leakage_ma"], "Corrente de fuga", "Fuga (mA)"),
                ]
                available_groups = [(columns, title, unit) for columns, title, unit in auxiliary_groups if any(column in curve_data for column in columns)]
                for group_index in range(0, len(available_groups), 2):
                    group_columns = st.columns(2)
                    for target, (columns, title, unit) in zip(group_columns, available_groups[group_index:group_index + 2]):
                        columns = [column for column in columns if column in curve_data]
                        chart_data = curve_data[["timestamp", *columns]].melt("timestamp", var_name="series", value_name="value")
                        labels = {
                            "daily_energy_kwh": "Geração do dia",
                            "grid_voltage_v": "Tensão monitorada",
                            "frequency_hz": "Frequência",
                            "heatsink_temp_c": "Inversor / radiador",
                            "internal_temp_c": "Interna",
                            "insulation_kohm": "Isolamento",
                            "leakage_ma": "Fuga",
                            "phase_a_voltage_v": "Fase A",
                            "phase_b_voltage_v": "Fase B",
                            "phase_c_voltage_v": "Fase C",
                        }
                        chart_data["series"] = chart_data["series"].map(lambda value: labels.get(value, value))
                        chart = (
                            alt.Chart(chart_data)
                            .mark_line(strokeWidth=2)
                            .encode(
                                x=alt.X("timestamp:T", title=None, axis=alt.Axis(format="%Hh")),
                                y=alt.Y("value:Q", title=unit, scale=alt.Scale(zero=False)),
                                color=alt.Color("series:N", title=None, legend=alt.Legend(orient="top")),
                                tooltip=[alt.Tooltip("timestamp:T", format="%H:%M"), "series:N", alt.Tooltip("value:Q", format=".2f")],
                            )
                            .properties(height=230, title=title)
                        )
                        target.altair_chart(chart)

            st.subheader("Diagnóstico técnico", icon=":material/troubleshoot:")
            if curve_result["issues"]:
                issue_df = pd.DataFrame(
                    [
                        {
                            "Severidade": issue.severity,
                            "Parâmetro": issue.parameter,
                            "Evidência": issue.finding,
                            "Possível causa": issue.possible_cause,
                            "Próxima ação": issue.recommendation,
                        }
                        for issue in curve_result["issues"]
                    ]
                )
                st.dataframe(issue_df, hide_index=True)
                csv_download(issue_df, f"diagnostico-{summary['analysis_date']}.csv", "Baixar achados em CSV")
            else:
                st.info("Os limites avaliados não apontaram desvios evidentes. Continue comparando com clima, histórico e alarmes.")

            with st.expander("Dados reconhecidos e prévia da planilha", icon=":material/table_view:"):
                st.dataframe(curve_data.head(300), hide_index=True)
                csv_download(curve_data, f"curva-normalizada-{summary['analysis_date']}.csv", "Baixar dados normalizados")

            try:
                curve_pdf = inverter_curve_pdf(
                    plant_id,
                    inverter_name,
                    uploaded_curve.name,
                    file_bytes,
                    selected_sheet,
                    mapping_json,
                    float(nominal_power),
                    float(nominal_voltage),
                )
                st.download_button(
                    "Baixar relatório técnico em PDF",
                    data=curve_pdf,
                    file_name=f"relatorio-curva-inversor-{summary['analysis_date']}.pdf",
                    mime="application/pdf",
                    icon=":material/picture_as_pdf:",
                    type="primary",
                    key=f"curve_pdf_{plant_id}_{uploaded_curve.name}",
                )
            except Exception:
                st.error("A análise foi concluída, mas não foi possível montar o PDF. Atualize a página e tente novamente.")

            if st.button("Salvar análise no histórico", type="primary", icon=":material/save:", key=f"save_curve_{plant_id}_{uploaded_curve.name}"):
                save_curve_analysis(plant_id, inverter_name, uploaded_curve.name, curve_result)
                flash("Análise da curva salva no histórico da usina.")
                st.rerun()
        except CurveAnalysisError as exc:
            st.error(str(exc), icon=":material/error:")
        except Exception:
            st.error("Não foi possível concluir a análise deste arquivo. Confira o mapeamento das colunas e tente novamente.")

    st.divider()
    st.subheader("Histórico de análises", icon=":material/history:")
    curve_history = load_curve_history(plant_id)
    if curve_history:
        history_df = pd.DataFrame(curve_history).rename(
            columns={
                "analysis_date": "Data",
                "inverter_name": "Inversor",
                "source_filename": "Arquivo",
                "sample_count": "Amostras",
                "daily_energy_kwh": "Geração",
                "peak_power_kw": "Pico",
                "health_status": "Situação",
                "issue_count": "Achados",
                "created_at": "Salvo em",
            }
        )
        st.dataframe(
            history_df.drop(columns=["id"]),
            hide_index=True,
            column_config={
                "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Geração": st.column_config.NumberColumn(format="%.2f kWh"),
                "Pico": st.column_config.NumberColumn(format="%.2f kW"),
                "Salvo em": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
            },
        )
        history_map = {
            f"{row['analysis_date']} · {row.get('inverter_name') or 'Inversor'} · #{row['id']}": int(row["id"])
            for row in curve_history
        }
        selected_history = st.selectbox("Análise para excluir", list(history_map), key=f"curve_history_delete_{plant_id}")
        render_delete_control(
            "inverter_curve_analysis",
            history_map[selected_history],
            f"análise {selected_history}",
            state_keys=(f"curve_history_delete_{plant_id}",),
        )
    else:
        st.caption("Nenhuma análise de Excel foi salva para esta usina.")

with alarms_tab:
    alarms = load_equipment_alarms(plant_id)
    if alarms:
        severity_options = sorted({row["severity"] for row in alarms})
        selected_severities = st.pills(
            "Severidade",
            severity_options,
            default=severity_options,
            selection_mode="multi",
            key="alarm_severity",
        )
        filtered_alarms = [row for row in alarms if row["severity"] in selected_severities]
        alarm_df = pd.DataFrame(filtered_alarms).rename(
            columns={
                "occurred_at": "Data e hora",
                "code": "Código",
                "severity": "Severidade",
                "title": "Ocorrência",
                "message": "Detalhes",
                "status": "Status",
                "source_name": "Equipamento",
                "provider": "Origem",
            }
        )
        st.dataframe(
            alarm_df,
            hide_index=True,
            column_config={"Data e hora": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")},
        )
        csv_download(alarm_df, f"falhas-e-alarmes-{reading_day.isoformat()}.csv", "Exportar relatório de falhas")
    else:
        empty_state(
            "Nenhuma falha registrada",
            "Os alarmes recebidos das APIs aparecerão aqui com código, severidade e situação.",
            ":material/check_circle:",
        )

with api_tab:
    st.info(
        "A análise usa somente APIs em nuvem. Não é necessário instalar programa, cabo ou computador na usina.",
        icon=":material/cloud:",
    )
    st.subheader("Fontes configuradas", icon=":material/hub:")
    if sources:
        source_df = pd.DataFrame(sources).rename(
            columns={
                "name": "Fonte",
                "provider": "Fabricante / adaptador",
                "credential_hint": "Credencial",
                "device_sn": "Número de série",
                "status": "Status",
                "last_sync_at": "Última sincronização",
                "last_sync_status": "Resultado",
                "last_error": "Último erro",
            }
        ).drop(columns=["id"])
        st.dataframe(
            source_df,
            hide_index=True,
            column_config={"Última sincronização": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")},
        )
        synchronized_sources = [row for row in sources if row["provider"] == NORMALIZED_REST]
        if synchronized_sources:
            source_map = {
                f"{row['name']} · {row['provider']}": int(row["id"])
                for row in synchronized_sources
            }
            with st.container(border=True):
                st.subheader("Sincronizar equipamentos", icon=":material/sync:")
                with st.container(horizontal=True, vertical_alignment="bottom"):
                    sync_source = st.selectbox("Fonte", list(source_map), key="equipment_sync_source")
                    sync_day = st.date_input("Data", value=reading_day, key="equipment_sync_day")
                    if st.button("Sincronizar agora", type="primary", icon=":material/sync:"):
                        try:
                            with st.spinner("Consultando strings e alarmes do inversor..."):
                                result = sync_equipment_integration(source_map[sync_source], sync_day)
                            flash(
                                f"Sincronização concluída: {result.string_samples} amostras e {result.alarms} alarmes recebidos."
                            )
                            st.rerun()
                        except EquipmentAnalysisError as exc:
                            st.error(str(exc))
    else:
        st.info("Nenhuma fonte de equipamento foi configurada para esta usina.", icon=":material/info:")

    with st.expander("Adicionar API de equipamento", icon=":material/add:"):
        provider = st.selectbox("Fabricante / adaptador", EQUIPMENT_PROVIDERS, key="new_equipment_provider")
        profile = equipment_profile(provider)
        if profile:
            with st.container(border=True):
                st.subheader(f"{profile['brand']} · conexão por API", icon=":material/cloud_sync:")
                st.table(
                    [
                        {"Item": "Portal", "Detalhes": profile["portal"]},
                        {"Item": "Liberação", "Detalhes": profile["access"]},
                        {"Item": "Dados esperados", "Detalhes": profile["scope"]},
                        {"Item": "Detalhamento de strings", "Detalhes": profile["string_scope"]},
                    ],
                    border="horizontal",
                )
                st.link_button(
                    "Abrir portal ou documentação oficial",
                    profile["documentation_url"],
                    icon=":material/menu_book:",
                )
        if provider != NORMALIZED_REST:
            st.warning(
                "Cadastre somente credenciais oficiais destinadas a integração. A sincronização será liberada "
                "quando o fabricante autorizar a conta e fornecer os endpoints do seu contrato. A disponibilidade "
                "de dados por string varia por marca e modelo.",
                icon=":material/info:",
            )
        with st.form("new_equipment_integration"):
            name = st.text_input(
                "Nome da fonte",
                placeholder="Ex.: Inversor 1 · telhado norte",
            )
            device_sn = st.text_input("Número de série / ID do inversor ou datalogger")
            base_url = st.text_input("Endereço-base HTTPS", placeholder="https://api.fabricante.com")
            auth_type = st.selectbox("Autenticação", AUTH_TYPES)
            api_key = st.text_input(
                "Usuário, client ID ou nome do cabeçalho",
                help="No modo API key, use por exemplo X-API-Key. No Basic Auth, informe o usuário.",
            )
            api_secret = st.text_input("Token, senha ou client secret", type="password")
            strings_path = st.text_input(
                "Endpoint de strings ou MPPTs",
                value="/equipment/{device_sn}/strings?date={date}",
                help="Use o caminho fornecido pela documentação da API. Marcadores: {device_sn} e {date}.",
            )
            alarms_path = st.text_input(
                "Endpoint de alarmes",
                value="/equipment/{device_sn}/alarms?date={date}",
                help="Use o caminho fornecido pela documentação da API. Marcadores: {device_sn} e {date}.",
            )
            if st.form_submit_button("Salvar fonte protegida", type="primary", icon=":material/lock:"):
                try:
                    create_equipment_integration(
                        plant_id=plant_id,
                        name=name,
                        provider=provider,
                        base_url=base_url,
                        auth_type=auth_type,
                        credential_key=api_key,
                        credential_secret=api_secret,
                        device_sn=device_sn,
                        strings_path=strings_path,
                        alarms_path=alarms_path,
                    )
                    flash("Fonte de equipamentos salva com a credencial protegida.")
                    st.rerun()
                except EquipmentAnalysisError as exc:
                    st.error(str(exc))

    with st.expander("Contrato esperado da API REST normalizada", icon=":material/data_object:"):
        st.caption(
            "O gateway pode adaptar qualquer fabricante para estes campos. Corrente, tensão e potência devem usar A, V e kW."
        )
        st.code(
            """{
  "data": [
    {
      "timestamp": "2026-09-06T10:15:00",
      "inverter": "INV 1",
      "mppt": "MPPT 2",
      "string": "S4",
      "current_a": 8.42,
      "voltage_v": 558.0,
      "power_kw": 4.70
    }
  ]
}""",
            language="json",
        )
        st.code(
            """{
  "data": [
    {
      "id": "alarm-9271",
      "timestamp": "2026-09-06T10:21:00",
      "code": "DC_LOW_CURRENT",
      "severity": "Alta",
      "title": "Corrente baixa na string S4",
      "message": "Verificar conectores e sombreamento.",
      "status": "Aberto"
    }
  ]
}""",
            language="json",
        )
