from datetime import date

import pandas as pd
import streamlit as st

from solar_crm.calculations import number_br, percent
from solar_crm.db import query, query_df
from solar_crm.monitoring import (
    DEFAULT_URLS,
    GROWATT,
    SOLARZ,
    SOLIS,
    SUPPORTED_PROVIDERS,
    MonitoringError,
    create_integration,
    discover_remote_plants,
    link_plant,
    sync_mapping,
    update_integration_credentials,
)
from solar_crm.ui import date_br, flash, month_label, page_intro, plant_options, render_delete_control, show_flash

page_intro("Use o SolarZ como central principal para importar usinas, geração diária e desempenho mensal diretamente para o SolarOS.")
show_flash()

connections = query(
    """SELECT id, name, provider, base_url, credential_hint, status,
              sync_interval_minutes, last_sync_at, last_sync_status, last_error
       FROM monitoring_integrations ORDER BY name"""
)
mappings = query(
    """SELECT pi.id, pi.plant_id, pi.integration_id, pi.remote_plant_id,
              pi.last_sync_at, pi.last_sync_status, pi.last_error,
              p.name AS plant_name, c.name AS client_name, mi.name AS integration_name,
              mi.provider, rp.name AS remote_name
       FROM plant_integrations pi
       JOIN plants p ON p.id=pi.plant_id
       JOIN clients c ON c.id=p.client_id
       JOIN monitoring_integrations mi ON mi.id=pi.integration_id
       LEFT JOIN remote_plants rp ON rp.integration_id=pi.integration_id
                                 AND rp.remote_plant_id=pi.remote_plant_id
       WHERE pi.status='Ativo' ORDER BY c.name, p.name"""
)
last_success = max(
    (row["last_sync_at"] for row in connections if row["last_sync_status"] == "Sucesso" and row["last_sync_at"]),
    default=None,
)
errors = sum(1 for row in connections if row["status"] == "Erro")

with st.container(horizontal=True):
    st.metric("Contas conectadas", sum(1 for row in connections if row["status"] == "Conectada"), border=True)
    st.metric("Usinas vinculadas", len(mappings), border=True)
    st.metric("Última sincronização", date_br(last_success[:10]) if last_success else "Ainda não realizada", border=True)
    st.metric("Conexões com erro", errors, border=True)

accounts_tab, mapping_tab, sync_tab, history_tab = st.tabs([
    ":material/key: Contas de API",
    ":material/link: Vincular usinas",
    ":material/sync: Sincronizar",
    ":material/history: Histórico",
])

with accounts_tab:
    with st.container(border=True):
        st.subheader("SolarZ Monitoramento · integração principal", icon=":material/verified:")
        st.write(
            "Centralize usinas de diferentes fabricantes em uma única conta e envie ao SolarOS "
            "a geração diária e a meta de geração usada no desempenho mensal."
        )
        st.success("Conector oficial ativo no SolarOS.", icon=":material/check_circle:")
        st.markdown(
            "Para conectar, gere as credenciais em **SolarZ > Configurações > Usuário de API > Gerar Usuário de API**. "
            "A senha aparece uma única vez. [Abrir orientação oficial da SolarZ](https://monitoramento.ajuda.solarz.com.br/monitoramento/api-solarz)"
        )

    with st.expander("Outros conectores diretos", icon=":material/hub:"):
        supported_left, supported_right = st.columns(2)
        with supported_left.container(border=True):
            st.subheader("Growatt OpenAPI", icon=":material/check_circle:")
            st.write("Conector direto para descoberta de usinas e geração diária/mensal.")
            st.caption("Credencial necessária: API Token do portal Growatt.")
        with supported_right.container(border=True):
            st.subheader("SolisCloud", icon=":material/check_circle:")
            st.write("Conector direto com assinatura segura HMAC-SHA1 e energia diária.")
            st.caption("Credenciais necessárias: API ID e API Secret.")

    with st.expander("Adicionar conta de monitoramento", icon=":material/add:"):
        provider = st.selectbox("Fabricante / portal", SUPPORTED_PROVIDERS, key="new_integration_provider")
        with st.form(f"new_integration_{provider}"):
            connection_name = st.text_input(
                "Nome da conexão",
                placeholder="Ex.: SolarZ principal" if provider == SOLARZ else "Ex.: Conta instalador SolarOS",
            )
            base_url = st.text_input("Endereço da API", value=DEFAULT_URLS[provider])
            key_label = "Usuário de API" if provider == SOLARZ else "API ID"
            key_help = (
                "Usuário exclusivo gerado na área Usuário de API da SolarZ."
                if provider == SOLARZ
                else "Na Growatt este campo não é utilizado. Na SolisCloud, informe o KeyID/API ID."
            )
            api_id = st.text_input(
                key_label,
                disabled=provider == GROWATT,
                help=key_help,
            )
            secret_label = "Senha da API" if provider == SOLARZ else ("API Token" if provider == GROWATT else "API Secret")
            secret = st.text_input(
                secret_label,
                type="password",
                help="A credencial será protegida pelo Windows e nunca será exibida em relatórios.",
            )
            interval = st.number_input("Intervalo planejado de sincronização (minutos)", min_value=15, value=60, step=15)
            if st.form_submit_button("Salvar conexão", type="primary", icon=":material/lock:"):
                try:
                    create_integration(connection_name, provider, base_url, api_id, secret, int(interval))
                    flash("Conexão salva com a credencial protegida. Agora teste o acesso ao portal.")
                    st.rerun()
                except MonitoringError as exc:
                    st.error(str(exc))

    if connections:
        st.subheader("Contas cadastradas", icon=":material/cloud_done:")
        account_df = pd.DataFrame(connections).rename(columns={
            "name": "Conexão",
            "provider": "Portal",
            "base_url": "Endereço",
            "credential_hint": "Credencial",
            "status": "Status",
            "sync_interval_minutes": "Intervalo (min)",
            "last_sync_at": "Última sincronização",
            "last_sync_status": "Resultado",
            "last_error": "Último erro",
        })[["Conexão", "Portal", "Endereço", "Credencial", "Status", "Intervalo (min)", "Última sincronização", "Resultado", "Último erro"]]
        st.dataframe(account_df, hide_index=True)

        connection_map = {f"{row['name']} · {row['provider']}": row["id"] for row in connections}
        selected_connection = st.selectbox("Conta para testar", list(connection_map), key="connection_test")
        with st.container(horizontal=True):
            if st.button("Testar e buscar usinas", type="primary", icon=":material/travel_explore:"):
                try:
                    with st.spinner("Consultando o portal do fabricante..."):
                        found = discover_remote_plants(connection_map[selected_connection])
                    st.success(f"Conexão validada. {len(found)} usina(s) encontrada(s).", icon=":material/check_circle:")
                    st.dataframe(
                        pd.DataFrame([{
                            "Usina remota": row.name,
                            "ID remoto": row.remote_id,
                            "Potência": row.capacity_kwp,
                            "Potência atual": row.current_power_kw,
                            "Energia acumulada": row.total_energy_kwh,
                            "Status": row.status,
                        } for row in found]),
                        hide_index=True,
                        column_config={
                            "Potência": st.column_config.NumberColumn(format="%.2f kWp"),
                            "Potência atual": st.column_config.NumberColumn(format="%.2f kW"),
                            "Energia acumulada": st.column_config.NumberColumn(format="%.0f kWh"),
                        },
                    )
                except MonitoringError as exc:
                    st.error(str(exc))

        with st.expander("Substituir credenciais", icon=":material/password:"):
            credential_connection = st.selectbox("Conta", list(connection_map), key="credential_connection")
            credential_row = next(row for row in connections if row["id"] == connection_map[credential_connection])
            with st.form("replace_api_credentials"):
                replace_key_label = "Novo usuário de API" if credential_row["provider"] == SOLARZ else "Novo API ID"
                replace_secret_label = "Nova senha da API" if credential_row["provider"] == SOLARZ else "Novo token ou API Secret"
                new_api_id = st.text_input(replace_key_label, type="password", disabled=credential_row["provider"] == GROWATT)
                new_secret = st.text_input(replace_secret_label, type="password")
                st.caption("Campos vazios preservam a credencial atual.")
                if st.form_submit_button("Atualizar credenciais", icon=":material/lock_reset:"):
                    try:
                        update_integration_credentials(credential_row["id"], new_api_id, new_secret)
                        flash("Credenciais atualizadas com segurança.")
                        st.rerun()
                    except MonitoringError as exc:
                        st.error(str(exc))
        connection_to_delete = next(row for row in connections if row["id"] == connection_map[selected_connection])
        render_delete_control(
            "integration",
            connection_to_delete["id"],
            f"conta de integração {connection_to_delete['name']}",
            extra_warning="As credenciais, usinas remotas, vínculos e o histórico desta conta serão removidos.",
        )
    else:
        st.info("Cadastre a primeira conta de API para iniciar a integração.", icon=":material/info:")

    with st.container(border=True):
        st.subheader("Estratégia de integração", icon=":material/route:")
        st.write("O SolarZ passa a ser o caminho recomendado para reunir fabricantes diferentes em uma só integração.")
        st.write("Conectores diretos adicionais poderão ser mantidos para contas que não estejam cadastradas no SolarZ.")

with mapping_tab:
    remote_plants = query(
        """SELECT rp.*, mi.name AS integration_name, mi.provider
           FROM remote_plants rp JOIN monitoring_integrations mi ON mi.id=rp.integration_id
           ORDER BY mi.name, rp.name"""
    )
    local_plants = query(
        """SELECT p.id, p.name, c.name AS client_name FROM plants p
           JOIN clients c ON c.id=p.client_id WHERE p.status!='Desativada'
           ORDER BY c.name, p.name"""
    )
    if not remote_plants:
        st.info("Na aba Contas de API, teste a conexão para buscar as usinas do fabricante.", icon=":material/info:")
    elif not local_plants:
        st.warning("Cadastre uma usina no SolarOS antes de criar o vínculo.", icon=":material/warning:")
    else:
        st.subheader("Correspondência entre as usinas", icon=":material/link:")
        st.caption("Cada usina do SolarOS pode apontar para uma usina remota. Isso impede duplicidade de geração.")
        local_map = plant_options(local_plants)
        remote_map = {
            f"{row['integration_name']} · {row['name']} · ID {row['remote_plant_id']}": row
            for row in remote_plants
        }
        with st.form("link_monitoring_plant"):
            local_label = st.selectbox("Usina no SolarOS", list(local_map))
            remote_label = st.selectbox("Usina encontrada no portal", list(remote_map))
            device_sn = st.text_input("Número de série do inversor/datalogger", help="Opcional nesta etapa; útil para alarmes por equipamento.")
            if st.form_submit_button("Vincular usinas", type="primary", icon=":material/link:"):
                remote = remote_map[remote_label]
                try:
                    link_plant(local_map[local_label], remote["integration_id"], remote["remote_plant_id"], device_sn)
                    flash("Usina vinculada ao portal de monitoramento.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Não foi possível criar o vínculo: {exc}")

    if mappings:
        linked_df = pd.DataFrame(mappings).rename(columns={
            "client_name": "Cliente",
            "plant_name": "Usina SolarOS",
            "provider": "Portal",
            "remote_name": "Usina remota",
            "remote_plant_id": "ID remoto",
            "last_sync_at": "Última sincronização",
            "last_sync_status": "Resultado",
            "last_error": "Erro",
        })[["Cliente", "Usina SolarOS", "Portal", "Usina remota", "ID remoto", "Última sincronização", "Resultado", "Erro"]]
        st.dataframe(linked_df, hide_index=True)
        mapping_delete_map = {
            f"{row['client_name']} · {row['plant_name']} · {row['provider']}": row
            for row in mappings
        }
        mapping_delete_label = st.selectbox(
            "Vínculo para administrar",
            list(mapping_delete_map),
            key="mapping_delete_selector",
        )
        mapping_to_delete = mapping_delete_map[mapping_delete_label]
        render_delete_control(
            "plant_integration",
            mapping_to_delete["id"],
            f"vínculo de {mapping_to_delete['plant_name']} com {mapping_to_delete['provider']}",
        )

with sync_tab:
    if not mappings:
        st.info("Vincule ao menos uma usina antes da primeira sincronização.", icon=":material/info:")
    else:
        mapping_map = {
            f"{row['client_name']} · {row['plant_name']} · {row['provider']}": row
            for row in mappings
        }
        selected_mapping_label = st.selectbox("Usina para sincronizar", list(mapping_map), key="sync_mapping")
        selected_mapping = mapping_map[selected_mapping_label]
        sync_month = st.date_input("Mês a importar", value=date.today().replace(day=1), key="sync_month")
        st.caption("No SolarZ, o desempenho usa a geração esperada fornecida pelo próprio portal. Consumo, tarifa e valor da fatura permanecem sob sua conferência.")
        if st.button("Sincronizar geração", type="primary", icon=":material/sync:"):
            try:
                with st.status("Sincronizando dados do fabricante...", expanded=True) as status:
                    st.write("Autenticando a conta de API")
                    st.write("Buscando a energia diária da usina")
                    result = sync_mapping(selected_mapping["id"], sync_month.replace(day=1).isoformat())
                    status.update(label="Sincronização concluída", state="complete", expanded=False)
                st.success(
                    f"{result.records_received} dia(s) importado(s) · {number_br(result.generation_kwh, 1)} kWh · desempenho {percent(result.performance_pct)}",
                    icon=":material/check_circle:",
                )
            except MonitoringError as exc:
                st.error(str(exc))

        daily = query_df(
            """SELECT reading_date AS Data, generation_kwh AS Geração,
                      peak_power_kw AS 'Pico de potência', alarms_count AS Alarmes, source AS Fonte
               FROM telemetry_daily WHERE plant_id=? AND substr(reading_date,1,7)=?
               ORDER BY reading_date""",
            (selected_mapping["plant_id"], sync_month.strftime("%Y-%m")),
        )
        if not daily.empty:
            daily["Data"] = pd.to_datetime(daily["Data"])
            st.line_chart(daily, x="Data", y="Geração", x_label="Dia", y_label="Geração (kWh)")
            st.dataframe(
                daily.sort_values("Data", ascending=False),
                hide_index=True,
                column_config={
                    "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "Geração": st.column_config.NumberColumn(format="%.1f kWh"),
                    "Pico de potência": st.column_config.NumberColumn(format="%.2f kW"),
                },
            )

with history_tab:
    logs = query_df(
        """SELECT l.started_at AS Início, l.finished_at AS Término,
                  c.name AS Cliente, p.name AS Usina, mi.provider AS Portal,
                  l.reference_month AS Mês, l.status AS Resultado,
                  l.records_received AS Registros, l.generation_kwh AS Geração,
                  l.message AS Mensagem
           FROM integration_sync_logs l
           JOIN monitoring_integrations mi ON mi.id=l.integration_id
           LEFT JOIN plants p ON p.id=l.plant_id
           LEFT JOIN clients c ON c.id=p.client_id
           ORDER BY l.started_at DESC LIMIT 200"""
    )
    if logs.empty:
        st.info("Nenhuma sincronização executada até agora.", icon=":material/info:")
    else:
        logs["Mês"] = logs["Mês"].map(month_label)
        st.dataframe(
            logs,
            hide_index=True,
            column_config={
                "Registros": st.column_config.NumberColumn(format="%d dias"),
                "Geração": st.column_config.NumberColumn(format="%.1f kWh"),
            },
        )

st.caption("Segurança: as credenciais são criptografadas pelo Windows para o usuário atual e nunca são incluídas em exportações, tabelas ou relatórios de clientes.")
