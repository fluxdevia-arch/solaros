from __future__ import annotations

import json
import re
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from solar_crm.calculations import number_br
from solar_crm.document_cache import inverter_curve_pdf
from solar_crm.inverter_curve import FIELD_LABELS, CurveAnalysisError, analyze_inverter_curve, suggest_column_mapping, workbook_preview
from solar_crm.ui import csv_download, page_intro


@st.cache_data(ttl="1h", max_entries=24, show_spinner=False)
def _analyze(
    content: bytes,
    filename: str,
    sheet_name: str,
    mapping_json: str,
    nominal_power_kw: float,
    nominal_voltage_v: float,
    selected_day: str = "",
):
    return analyze_inverter_curve(
        content,
        filename,
        sheet_name=sheet_name,
        column_mapping=json.loads(mapping_json),
        nominal_power_kw=nominal_power_kw,
        nominal_grid_voltage_v=nominal_voltage_v,
        selected_day=date.fromisoformat(selected_day) if selected_day else None,
    )


def _curve_chart(data: pd.DataFrame, fields: list[str], labels: dict[str, str], title: str, unit: str):
    fields = [field for field in fields if field in data and data[field].notna().any()]
    if not fields:
        return None
    chart_data = data[["timestamp", *fields]].melt("timestamp", var_name="series", value_name="value")
    chart_data["series"] = chart_data["series"].map(lambda value: labels.get(value, value))
    return (
        alt.Chart(chart_data)
        .mark_line(strokeWidth=2.2)
        .encode(
            x=alt.X("timestamp:T", title=None, axis=alt.Axis(format="%H:%M")),
            y=alt.Y("value:Q", title=unit, scale=alt.Scale(zero=False)),
            color=alt.Color("series:N", title=None, legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("timestamp:T", title="Horário", format="%d/%m %H:%M"), "series:N", alt.Tooltip("value:Q", title=unit, format=".2f")],
        )
        .properties(height=300, title=title)
        .interactive(bind_y=False)
    )


page_intro(
    "Faça diagnósticos diários ou mensais diretamente do Excel do inversor, sem cadastrar cliente ou usina."
)

with st.container(border=True):
    st.subheader("Identificação do relatório", icon=":material/badge:")
    left, right = st.columns(2)
    with left:
        client_name = st.text_input("Nome do cliente", placeholder="Ex.: Fazenda Boa Esperança")
        client_document = st.text_input("Documento do cliente", placeholder="CPF ou CNPJ (opcional)")
        address = st.text_input("Endereço da instalação")
        plant_name = st.text_input("Nome da usina / instalação", value="Instalação analisada")
        unit_code = st.text_input("Unidade consumidora", placeholder="Opcional")
    with right:
        inverter_brand = st.text_input("Marca do inversor", placeholder="Ex.: Solis, Growatt, Sungrow")
        inverter_model = st.text_input("Modelo / identificação do inversor", placeholder="Ex.: SP001705G24A0004")
        installed_kwp = st.number_input("Potência instalada dos módulos (kWp)", min_value=0.0, value=0.0, step=0.5)
        nominal_power_kw = st.number_input("Potência nominal do inversor (kW)", min_value=0.0, value=0.0, step=0.5)
        module_count = st.number_input("Quantidade de painéis", min_value=0, value=0, step=1)
        module_power_wp = st.number_input("Potência de cada painel (Wp)", min_value=0.0, value=0.0, step=5.0)
        nominal_voltage = st.number_input("Tensão nominal fase-neutro (V)", min_value=100.0, max_value=500.0, value=220.0, step=1.0)

uploaded = st.file_uploader(
    "Relatório Excel exportado pelo inversor",
    type=["xlsx"],
    help="Pode conter um único dia ou vários dias. A ordem das colunas não importa.",
)

if uploaded is None:
    st.info("Preencha a identificação, envie o Excel e o sistema montará a análise automaticamente.", icon=":material/upload_file:")
    st.stop()

content = uploaded.getvalue()
try:
    sheet_names, preview, default_sheet = workbook_preview(content)
    sheet_name = st.selectbox("Planilha com a telemetria", sheet_names, index=sheet_names.index(default_sheet))
    _, preview, _ = workbook_preview(content, sheet_name)
    automatic_mapping = suggest_column_mapping(list(preview.columns))
    manual_mapping: dict[str, str] = {}
    with st.expander("Conferir campos reconhecidos", icon=":material/account_tree:"):
        mapping_df = pd.DataFrame([
            {"Dado técnico": FIELD_LABELS.get(field, field.replace("_", " ").title()), "Coluna do Excel": column}
            for field, column in automatic_mapping.items()
        ])
        st.dataframe(mapping_df, hide_index=True)
        st.caption("Ajuste somente se algum campo essencial tiver sido associado incorretamente.")
        options = ["— Não informado —", *map(str, preview.columns)]
        adjustable_fields = [
            "timestamp", "active_power_kw", "pv_power_kw", "daily_energy_kwh", "total_energy_mwh",
            "frequency_hz", "grid_voltage_v", "internal_temp_c", "power_factor", "fault_code", "warning_code",
        ]
        mapping_columns = st.columns(2)
        for index, field in enumerate(adjustable_fields):
            default = automatic_mapping.get(field)
            selected = mapping_columns[index % 2].selectbox(
                FIELD_LABELS[field],
                options,
                index=options.index(default) if default in options else 0,
                key=f"standalone_map_{field}_{uploaded.name}",
            )
            if selected != options[0]:
                manual_mapping[field] = selected

    mapping_json = json.dumps(manual_mapping, ensure_ascii=False, sort_keys=True)
    with st.spinner("Lendo todas as amostras do arquivo..."):
        full_result = _analyze(
            content,
            uploaded.name,
            sheet_name,
            mapping_json,
            float(nominal_power_kw),
            float(nominal_voltage),
        )
except CurveAnalysisError as exc:
    st.error(str(exc), icon=":material/error:")
    st.stop()
except Exception:
    st.error("Não foi possível processar este Excel. Confira o mapeamento e tente novamente.", icon=":material/error:")
    st.stop()

available_days = full_result["available_days"]
supports_period = len(available_days) > 1
mode_options = ["Análise do período / mês", "Análise diária"] if supports_period else ["Análise diária"]
analysis_mode = st.segmented_control("Tipo de diagnóstico", mode_options, default=mode_options[0], selection_mode="single")
selected_day = available_days[-1]
if supports_period:
    selected_day = st.selectbox(
        "Dia para visualizar as curvas detalhadas",
        available_days,
        index=len(available_days) - 1,
        format_func=lambda value: value.strftime("%d/%m/%Y"),
    )

if analysis_mode == "Análise diária":
    with st.spinner("Preparando o diagnóstico do dia selecionado..."):
        result = _analyze(
            content,
            uploaded.name,
            sheet_name,
            mapping_json,
            float(nominal_power_kw),
            float(nominal_voltage),
            selected_day.isoformat(),
        )
else:
    result = full_result

detail_result = result
if analysis_mode != "Análise diária" and supports_period:
    detail_result = _analyze(
        content,
        uploaded.name,
        sheet_name,
        mapping_json,
        float(nominal_power_kw),
        float(nominal_voltage),
        selected_day.isoformat(),
    )

summary = result["summary"]
coverage = result["coverage"]
if summary["health_status"] == "Crítica":
    st.error("Foram encontrados indícios que exigem verificação prioritária.", icon=":material/error:")
elif summary["health_status"] == "Atenção":
    st.warning("Foram encontrados desvios que merecem conferência técnica.", icon=":material/warning:")
else:
    st.success("Nenhuma anomalia evidente foi encontrada nos campos disponíveis.", icon=":material/check_circle:")

with st.container(horizontal=True):
    st.metric("Situação", summary["health_status"], border=True)
    st.metric("Geração analisada", f"{number_br(summary['period_energy_kwh'], 2)} kWh", border=True)
    st.metric("Dias", summary["day_count"], border=True)
    st.metric("Média diária", f"{number_br(summary['average_daily_energy_kwh'], 2)} kWh", border=True)
    st.metric("Pico", f"{number_br(summary['peak_power_kw'], 2)} kW", border=True)
    st.metric("Amostras", summary["sample_count"], border=True)

if analysis_mode != "Análise diária" and not result["daily_summary"].empty:
    daily = result["daily_summary"].copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily_chart = (
        alt.Chart(daily)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("date:T", title=None, axis=alt.Axis(format="%d/%m")),
            y=alt.Y("energy_kwh:Q", title="Geração (kWh)"),
            color=alt.Color("energy_kwh:Q", scale=alt.Scale(range=["#b7d8c9", "#0B7A53"]), legend=None),
            tooltip=[alt.Tooltip("date:T", title="Data", format="%d/%m/%Y"), alt.Tooltip("energy_kwh:Q", title="Geração", format=".2f"), alt.Tooltip("peak_power_kw:Q", title="Pico", format=".2f")],
        )
        .properties(height=320, title="Geração diária no período")
    )
    st.altair_chart(daily_chart)

st.subheader(f"Curvas detalhadas de {selected_day.strftime('%d/%m/%Y')}", icon=":material/show_chart:")
detail_data = detail_result["data"]
labels = {"active_power_kw": "Potência ativa", "pv_power_kw": "Potência FV", "daily_energy_kwh": "Energia acumulada"}
power_chart = _curve_chart(detail_data, ["active_power_kw", "pv_power_kw"], labels, "Potência", "kW")
if power_chart is not None:
    st.altair_chart(power_chart)
energy_chart = _curve_chart(detail_data, ["daily_energy_kwh"], labels, "Energia acumulada", "kWh")
if energy_chart is not None:
    st.altair_chart(energy_chart)

mppt_current = sorted(field for field in detail_data if re.match(r"mppt_\d+_current_a", field) and detail_data[field].notna().any())
mppt_voltage = sorted(field for field in detail_data if re.match(r"mppt_\d+_voltage_v", field) and detail_data[field].notna().any())
mppt_labels = {field: f"MPPT {field.split('_')[1]}" for field in [*mppt_current, *mppt_voltage]}
chart_left, chart_right = st.columns(2)
current_chart = _curve_chart(detail_data, mppt_current, mppt_labels, "Correntes CC / MPPT", "A")
voltage_chart = _curve_chart(detail_data, mppt_voltage, mppt_labels, "Tensões CC / MPPT", "V")
if current_chart is not None:
    chart_left.altair_chart(current_chart)
if voltage_chart is not None:
    chart_right.altair_chart(voltage_chart)

phase_voltage = [field for field in detail_data if re.match(r"phase_[abc]_voltage_v", field)]
phase_current = [field for field in detail_data if re.match(r"phase_[abc]_current_a", field)]
phase_labels = {field: f"Fase {field.split('_')[1].upper()}" for field in [*phase_voltage, *phase_current]}
ac_left, ac_right = st.columns(2)
phase_voltage_chart = _curve_chart(detail_data, phase_voltage, phase_labels, "Tensões de fase", "V")
phase_current_chart = _curve_chart(detail_data, phase_current, phase_labels, "Correntes de fase", "A")
if phase_voltage_chart is not None:
    ac_left.altair_chart(phase_voltage_chart)
if phase_current_chart is not None:
    ac_right.altair_chart(phase_current_chart)

temperature_fields = [field for field in detail_data if field.endswith("_temp_c")]
temperature_labels = {
    "internal_temp_c": "Interna", "boost_temp_c": "Boost",
    "igbt_u_temp_c": "IGBT U", "igbt_v_temp_c": "IGBT V", "igbt_w_temp_c": "IGBT W",
}
temperature_chart = _curve_chart(detail_data, temperature_fields, temperature_labels, "Temperaturas", "°C")
if temperature_chart is not None:
    st.altair_chart(temperature_chart)

with st.container(border=True):
    st.subheader("Cobertura do arquivo", icon=":material/data_check:")
    st.write(
        f"Foram identificadas **{coverage['mapped_column_count']} de {coverage['source_column_count']} colunas**, "
        f"com **{coverage['mppts_with_values']} entrada(s) CC/MPPT com dados**."
    )
    if coverage["recognized_string_channels"] and not coverage["string_channels_with_values"]:
        st.warning(
            f"Existem {coverage['recognized_string_channels']} colunas de strings no Excel, mas todas estão vazias. "
            "O sistema não inventa valores: analisa os canais CC/MPPT preenchidos e registra essa limitação no PDF."
        )
    elif result["string_summary"]:
        st.dataframe(pd.DataFrame(result["string_summary"]), hide_index=True)
    if coverage["unmapped_columns"]:
        st.caption("Colunas ainda não utilizadas: " + ", ".join(coverage["unmapped_columns"]))

st.subheader("Diagnóstico técnico", icon=":material/troubleshoot:")
if result["issues"]:
    issue_df = pd.DataFrame([
        {"Severidade": issue.severity, "Parâmetro": issue.parameter, "Evidência": issue.finding, "Possível causa": issue.possible_cause, "Ação recomendada": issue.recommendation}
        for issue in result["issues"]
    ])
    st.dataframe(issue_df, hide_index=True)
    csv_download(issue_df, f"diagnostico-{summary['date_start']}-{summary['date_end']}.csv", "Baixar achados em CSV")
else:
    st.info("Nenhuma anomalia evidente foi identificada pelos critérios e campos disponíveis.")

report_context = {
    "client_name": client_name,
    "client_document": client_document,
    "address": address,
    "plant_name": plant_name,
    "unit_code": unit_code,
    "inverter_brand": inverter_brand,
    "installed_kwp": float(installed_kwp),
    "module_count": int(module_count),
    "module_power_wp": float(module_power_wp),
}
selected_day_for_report = selected_day.isoformat() if analysis_mode == "Análise diária" else ""
pdf = inverter_curve_pdf(
    None,
    inverter_model or (summary.get("serial_numbers") or ["Inversor analisado"])[0],
    uploaded.name,
    content,
    sheet_name,
    mapping_json,
    float(nominal_power_kw),
    float(nominal_voltage),
    selected_day_for_report,
    json.dumps(report_context, ensure_ascii=False, sort_keys=True),
)
st.download_button(
    "Baixar relatório completo em PDF",
    data=pdf,
    file_name=f"diagnostico-inversor-{summary['date_start']}-{summary['date_end']}.pdf",
    mime="application/pdf",
    icon=":material/picture_as_pdf:",
    type="primary",
)

with st.expander("Dados normalizados", icon=":material/table_view:"):
    st.dataframe(result["data"].head(1000), hide_index=True)
    csv_download(result["data"], f"dados-normalizados-{summary['date_start']}-{summary['date_end']}.csv")
