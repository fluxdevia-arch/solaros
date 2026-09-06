from __future__ import annotations

import json
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

from solar_crm.calculations import number_br
from solar_crm.db import query
from solar_crm.equipment_analysis import (
    AUTH_TYPES,
    EQUIPMENT_PROVIDERS,
    NORMALIZED_REST,
    PHB85K_MT,
    EquipmentAnalysisError,
    analyze_string_samples,
    available_equipment_days,
    create_equipment_integration,
    equipment_profile,
    load_equipment_alarms,
    load_string_samples,
    phb85k_mt_collector_config,
    sync_equipment_integration,
)
from solar_crm.ui import csv_download, empty_state, flash, page_intro, show_flash, status_badge


page_intro(
    "Compare strings do mesmo MPPT, estime perdas e concentre falhas e alarmes enviados pela API do inversor."
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

overview_tab, strings_tab, alarms_tab, api_tab = st.tabs(
    [
        ":material/monitoring: Visão geral",
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
        source_map = {f"{row['name']} · {row['provider']}": int(row["id"]) for row in sources}
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
                st.subheader("Perfil reconhecido", icon=":material/memory:")
                with st.container(horizontal=True):
                    st.metric("Modelo", profile["model"], border=True)
                    st.metric("Potência nominal", f"{profile['nominal_power_kw']} kW", border=True)
                    st.metric("MPPTs", profile["mppt_count"], border=True)
                    st.metric("Strings", profile["string_count"], border=True)
                st.caption(
                    f"{profile['ac_output']} · {profile['transport']} · "
                    f"{profile['strings_per_mppt']} strings por MPPT."
                )
                st.link_button(
                    "Abrir manual oficial PHB",
                    profile["documentation_url"],
                    icon=":material/menu_book:",
                )
        if provider == PHB85K_MT:
            st.info(
                "O SolarOS Cloud recebe os dados por HTTPS. No local da usina, conecte um coletor ao RS485 "
                "do inversor e mantenha o Modbus somente para leitura.",
                icon=":material/cable:",
            )
            modbus_address = st.number_input(
                "Endereço Modbus do PHB",
                min_value=1,
                max_value=247,
                value=48,
                step=1,
                help="Foi preenchido como 48 a partir da identificação 048 informada. Confirme no InvApp/inversor.",
            )
            collector_config = phb85k_mt_collector_config(modbus_address=int(modbus_address))
            st.download_button(
                "Baixar configuração do coletor PHB",
                data=json.dumps(collector_config, ensure_ascii=False, indent=2),
                file_name="phb85k-mt-048-coletor.json",
                mime="application/json",
                icon=":material/download:",
            )
            st.warning(
                "A PHB confirma Modbus RTU, mas o manual público não traz a tabela de registradores nem todos "
                "os parâmetros seriais. O coletor não fará leituras até esses dados serem confirmados no mapa "
                "oficial do modelo.",
                icon=":material/warning:",
            )
        elif provider != NORMALIZED_REST:
            st.warning(
                "Esse fabricante exige um adaptador específico para converter os campos proprietários. "
                "Você pode salvar a configuração agora, mas a sincronização ficará pendente até o adaptador ser ativado.",
                icon=":material/info:",
            )
        with st.form("new_equipment_integration"):
            name = st.text_input(
                "Nome da fonte",
                value="PHB85K-MT · 048" if provider == PHB85K_MT else "",
                placeholder="Ex.: Inversor 1 · telhado norte",
            )
            base_url = st.text_input("Endereço-base HTTPS", placeholder="https://api.fabricante.com")
            device_sn = st.text_input(
                "Número de série / ID do inversor",
                value="048" if provider == PHB85K_MT else "",
            )
            auth_type = st.selectbox("Autenticação", AUTH_TYPES)
            api_key = st.text_input(
                "Usuário ou nome do cabeçalho",
                help="No modo API key, use por exemplo X-API-Key. No Basic Auth, informe o usuário.",
            )
            api_secret = st.text_input("Token, senha ou segredo", type="password")
            strings_path = st.text_input(
                "Endpoint de strings",
                value="/equipment/{device_sn}/strings?date={date}",
                help="Marcadores aceitos: {device_sn} e {date}.",
            )
            alarms_path = st.text_input(
                "Endpoint de alarmes",
                value="/equipment/{device_sn}/alarms?date={date}",
                help="Marcadores aceitos: {device_sn} e {date}.",
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
