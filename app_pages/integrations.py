from datetime import date

import pandas as pd
import streamlit as st

from solar_crm.calculations import number_br, percent
from solar_crm.db import query, query_df
from solar_crm.monitoring import (
    DEFAULT_URLS,
    PROVIDER_CATALOG,
    PROVIDER_PROFILES,
    SOLARZ,
    MonitoringError,
    connect_and_discover,
    discover_remote_plants,
    import_remote_plant,
    link_plant,
    sync_mapping,
    update_integration_credentials,
)
from solar_crm.ui import date_br, flash, month_label, page_intro, plant_options, render_delete_control, show_flash

page_intro("Conecte portais de fabricantes, importe usinas e centralize a geração diária no GRID Engenharia.")
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
    ":material/hub: Conexões",
    ":material/solar_power: Usinas importadas",
    ":material/sync: Sincronizar",
    ":material/history: Histórico",
])

with accounts_tab:
    st.subheader("Conecte seus portais de monitoramento", icon=":material/hub:")
    st.caption(
        "Escolha o portal, informe a credencial específica e deixe o GRID validar o acesso antes de salvar. "
        "Uma conexão pode importar várias usinas."
    )

    with st.container(horizontal=True, wrap=True):
        for step, label in enumerate(("Escolher o portal", "Informar credencial", "Validar acesso", "Importar usinas"), start=1):
            with st.container(border=True, width=205):
                st.badge(f"Passo {step}", color="blue")
                st.write(label)

    st.subheader("Portais disponíveis", icon=":material/apps:")
    for start in range(0, len(PROVIDER_CATALOG), 3):
        provider_columns = st.columns(3)
        for column, provider_name in zip(provider_columns, PROVIDER_CATALOG[start:start + 3]):
            profile = PROVIDER_PROFILES[provider_name]
            with column.container(border=True, height="stretch"):
                st.subheader(profile.portal_name, icon=":material/cloud:")
                if profile.connector_active:
                    st.badge("Conector ativo", color="green", icon=":material/check:")
                else:
                    st.badge("Aguardando fabricante", color="orange", icon=":material/pending:")
                st.caption(profile.credential_summary)
                st.caption(f"Autenticação: {getattr(profile, 'authentication_method', 'API oficial')}")

    st.subheader("Nova conexão", icon=":material/add_link:")
    provider = st.selectbox(
        "Portal ou fabricante",
        PROVIDER_CATALOG,
        key="new_integration_provider",
        format_func=lambda option: PROVIDER_PROFILES[option].portal_name,
    )
    profile = PROVIDER_PROFILES[provider]

    guide_column, form_column = st.columns([0.9, 1.5], vertical_alignment="top")
    with guide_column.container(border=True, height="stretch"):
        st.subheader("Onde conseguir a credencial", icon=":material/help:")
        for position, instruction in enumerate(profile.setup_steps, start=1):
            st.write(f"**{position}.** {instruction}")
        if profile.documentation_url:
            st.link_button(
                "Abrir orientação do portal",
                profile.documentation_url,
                icon=":material/open_in_new:",
            )
        portal_url = getattr(profile, "portal_url", "")
        support_url = getattr(profile, "support_url", "")
        if portal_url:
            st.link_button(
                "Abrir portal do fabricante",
                portal_url,
                icon=":material/login:",
            )
        if support_url:
            st.link_button(
                "Falar com o suporte oficial",
                support_url,
                icon=":material/support_agent:",
            )
        st.warning(
            "A senha comum usada para entrar no site do fabricante geralmente não é uma credencial de API.",
            icon=":material/key:",
        )

    with form_column.container(border=True, height="stretch"):
        if profile.connector_active:
            st.subheader(f"Conectar {profile.portal_name}", icon=":material/login:")
            with st.form(f"new_integration_{provider}"):
                connection_name = st.text_input(
                    "Nome desta conexão",
                    placeholder=f"Ex.: {profile.portal_name} principal",
                    help="Use um nome fácil de reconhecer caso tenha mais de uma conta no mesmo portal.",
                )
                api_id = ""
                if profile.key_label:
                    api_id = st.text_input(
                        profile.key_label,
                        placeholder=profile.key_placeholder,
                    )
                secret = st.text_input(
                    profile.secret_label,
                    type="password",
                    placeholder=profile.secret_placeholder,
                    help="A credencial será criptografada e nunca aparecerá nos relatórios.",
                )
                with st.expander("Configuração avançada", icon=":material/tune:"):
                    base_url = st.text_input("Endereço oficial da API", value=DEFAULT_URLS[provider])
                    interval = st.number_input(
                        "Intervalo planejado de sincronização (minutos)",
                        min_value=15,
                        value=60,
                        step=15,
                    )
                submitted = st.form_submit_button(
                    "Conectar, validar e importar usinas",
                    type="primary",
                    icon=":material/cloud_sync:",
                )
            if submitted:
                try:
                    with st.status("Validando a credencial no portal...", expanded=True) as status:
                        st.write("Conferindo o endereço oficial da API")
                        st.write("Autenticando sem salvar a credencial")
                        _, found = connect_and_discover(
                            connection_name,
                            provider,
                            base_url,
                            api_id,
                            secret,
                            int(interval),
                        )
                        st.write(f"Importando {len(found)} usina(s) disponível(is) para esta conta")
                        status.update(label="Portal conectado com sucesso", state="complete", expanded=False)
                    if found:
                        flash(f"Conexão validada e {len(found)} usina(s) importada(s).")
                    else:
                        flash(
                            "A conexão foi validada, mas o portal não liberou usinas para esta credencial. "
                            "Confira as permissões da conta.",
                            kind="warning",
                        )
                    st.rerun()
                except MonitoringError as exc:
                    st.error(str(exc), icon=":material/error:")
                    st.caption("Nada foi salvo. Corrija a credencial ou a permissão indicada e tente novamente.")
        else:
            st.subheader(f"Preparar conexão com {profile.portal_name}", icon=":material/pending_actions:")
            st.warning(profile.activation_note, icon=":material/admin_panel_settings:")
            authentication_method = getattr(profile, "authentication_method", "Credencial oficial do fabricante")
            support_request = getattr(profile, "support_request", "")
            st.markdown(f"**Método previsto:** {authentication_method}")
            st.table(
                {
                    "Etapa": ["1. Conta do portal", "2. Liberação da integração", "3. Conector GRID"],
                    "Responsável": ["Sua empresa", "Fabricante", "GRID Engenharia"],
                    "Situação": ["Confirmar acesso", "Solicitar credencial e documentação", "Aguardando dados oficiais"],
                }
            )
            if support_request:
                st.write("**Mensagem pronta para enviar ao suporte**")
                st.code(support_request, language=None, wrap_lines=True)
            st.info(
                "Quando o fabricante confirmar se a conta usa login, OAuth ou chave de API, o GRID poderá "
                "exibir exatamente esses campos, testar o acesso e importar as usinas.",
                icon=":material/info:",
            )
            st.caption(
                "Não envie senha ou chave secreta por mensagem. Ela será informada somente no formulário "
                "protegido quando o conector estiver ativo."
            )

    if connections:
        st.subheader("Portais conectados", icon=":material/cloud_done:")
        for row in connections:
            with st.container(border=True):
                summary, status_area, actions = st.columns([1.6, 0.8, 1.1], vertical_alignment="center")
                with summary:
                    st.subheader(row["name"])
                    st.caption(f"{row['provider']} · credencial {row['credential_hint']} · sincronização a cada {row['sync_interval_minutes']} min")
                with status_area:
                    badge_color = "green" if row["status"] == "Conectada" else ("red" if row["status"] == "Erro" else "blue")
                    st.badge(row["status"], color=badge_color)
                    if row["last_sync_at"]:
                        st.caption(f"Última sincronização: {date_br(row['last_sync_at'][:10])}")
                with actions:
                    if st.button(
                        "Atualizar usinas",
                        icon=":material/refresh:",
                        key=f"refresh_integration_{row['id']}",
                    ):
                        try:
                            with st.spinner(f"Consultando {row['provider']}..."):
                                found = discover_remote_plants(row["id"])
                            flash(f"{len(found)} usina(s) atualizada(s) em {row['name']}.")
                            st.rerun()
                        except MonitoringError as exc:
                            st.error(str(exc), icon=":material/error:")
                if row["last_error"]:
                    st.error(row["last_error"], icon=":material/error:")

        connection_map = {f"{row['name']} · {row['provider']}": row["id"] for row in connections}
        with st.expander("Administrar uma conexão", icon=":material/settings:"):
            selected_connection = st.selectbox("Conexão", list(connection_map), key="connection_admin")
            credential_row = next(row for row in connections if row["id"] == connection_map[selected_connection])
            credential_profile = PROVIDER_PROFILES[credential_row["provider"]]
            st.caption("Preencha apenas o que deseja substituir. Campos vazios preservam a credencial atual.")
            with st.form(f"replace_api_credentials_{credential_row['id']}"):
                new_api_id = ""
                if credential_profile.key_label:
                    new_api_id = st.text_input(
                        f"Novo {credential_profile.key_label}",
                        type="password",
                    )
                new_secret = st.text_input(
                    f"Novo {credential_profile.secret_label}",
                    type="password",
                )
                if st.form_submit_button("Atualizar credenciais", icon=":material/lock_reset:"):
                    try:
                        update_integration_credentials(credential_row["id"], new_api_id, new_secret)
                        flash("Credenciais atualizadas. Use Atualizar usinas para validar o novo acesso.")
                        st.rerun()
                    except MonitoringError as exc:
                        st.error(str(exc))
            render_delete_control(
                "integration",
                credential_row["id"],
                f"conta de integração {credential_row['name']}",
                extra_warning="As credenciais, usinas remotas, vínculos e o histórico desta conta serão removidos.",
            )
    else:
        st.info(
            "Nenhum portal conectado. Escolha um dos conectores acima para importar as primeiras usinas.",
            icon=":material/info:",
        )

with mapping_tab:
    remote_plants = query(
        """SELECT rp.*, mi.name AS integration_name, mi.provider,
                  pi.plant_id, p.name AS local_plant_name, c.name AS client_name
           FROM remote_plants rp
           JOIN monitoring_integrations mi ON mi.id=rp.integration_id
           LEFT JOIN plant_integrations pi ON pi.integration_id=rp.integration_id
              AND pi.remote_plant_id=rp.remote_plant_id AND pi.status='Ativo'
           LEFT JOIN plants p ON p.id=pi.plant_id
           LEFT JOIN clients c ON c.id=p.client_id
           ORDER BY mi.name, rp.name"""
    )
    local_plants = query(
        """SELECT p.id, p.name, c.name AS client_name FROM plants p
           JOIN clients c ON c.id=p.client_id WHERE p.status!='Desativada'
           ORDER BY c.name, p.name"""
    )
    clients = query("SELECT id, name FROM clients WHERE status='Ativo' ORDER BY name")
    if not remote_plants:
        st.info(
            "Conecte um portal na aba Conexões. As usinas liberadas pela credencial aparecerão aqui automaticamente.",
            icon=":material/info:",
        )
    else:
        linked_count = sum(1 for row in remote_plants if row["plant_id"])
        with st.container(horizontal=True):
            st.metric("Importadas dos portais", len(remote_plants), border=True)
            st.metric("Já vinculadas ao GRID", linked_count, border=True)
            st.metric("Aguardando vínculo", len(remote_plants) - linked_count, border=True)

        imported_df = pd.DataFrame([{
            "Portal": row["provider"],
            "Conta": row["integration_name"],
            "Usina importada": row["name"],
            "Potência (kWp)": row["capacity_kwp"],
            "Energia acumulada (kWh)": row["total_energy_kwh"],
            "Status remoto": row["remote_status"],
            "Cadastro no GRID": (
                f"{row['local_plant_name']} · {row['client_name']}" if row["plant_id"] else "Aguardando vínculo"
            ),
        } for row in remote_plants])
        st.dataframe(
            imported_df,
            hide_index=True,
            column_config={
                "Potência (kWp)": st.column_config.NumberColumn(format="%.2f kWp"),
                "Energia acumulada (kWh)": st.column_config.NumberColumn(format="%.0f kWh"),
            },
        )

        unlinked = [row for row in remote_plants if not row["plant_id"]]
        remote_map = {
            f"{row['integration_name']} · {row['name']} · ID {row['remote_plant_id']}": row
            for row in unlinked
        }
        if remote_map:
            st.subheader("Concluir a importação", icon=":material/link:")
            st.caption(
                "Escolha uma usina importada e diga se ela já existe no GRID ou se deve ser cadastrada agora."
            )
            remote_label = st.selectbox("Usina importada", list(remote_map), key="remote_plant_to_link")
            remote = remote_map[remote_label]
            link_mode = st.segmented_control(
                "O que deseja fazer?",
                ["Criar uma nova usina no GRID", "Vincular a uma usina já cadastrada"],
                default="Criar uma nova usina no GRID",
                required=True,
                key="remote_link_mode",
                wrap=True,
            )
            if link_mode == "Criar uma nova usina no GRID":
                if not clients:
                    st.warning("Cadastre primeiro o cliente que será o proprietário desta usina.", icon=":material/warning:")
                else:
                    client_map = {row["name"]: row["id"] for row in clients}
                    with st.form("import_remote_as_new_plant"):
                        client_label = st.selectbox("Cliente proprietário", list(client_map))
                        st.caption(
                            f"O GRID criará a usina **{remote['name']}** com {number_br(remote['capacity_kwp'], 2)} kWp. "
                            "Os demais dados técnicos poderão ser completados depois na ficha da usina."
                        )
                        if st.form_submit_button("Criar e vincular usina", type="primary", icon=":material/add_link:"):
                            try:
                                import_remote_plant(
                                    remote["integration_id"],
                                    remote["remote_plant_id"],
                                    client_map[client_label],
                                )
                                flash("Usina criada no GRID e vinculada ao portal.")
                                st.rerun()
                            except MonitoringError as exc:
                                st.error(str(exc))
            elif not local_plants:
                st.warning("Não há usinas locais disponíveis. Use a opção de criar uma nova usina.", icon=":material/warning:")
            else:
                local_map = plant_options(local_plants)
                with st.form("link_monitoring_plant"):
                    local_label = st.selectbox("Usina já cadastrada no GRID", list(local_map))
                    device_sn = st.text_input(
                        "Número de série do inversor/datalogger",
                        help="Opcional nesta etapa; útil para alarmes por equipamento.",
                    )
                    if st.form_submit_button("Vincular usinas", type="primary", icon=":material/link:"):
                        try:
                            link_plant(
                                local_map[local_label],
                                remote["integration_id"],
                                remote["remote_plant_id"],
                                device_sn,
                            )
                            flash("Usina vinculada ao portal de monitoramento.")
                            st.rerun()
                        except MonitoringError as exc:
                            st.error(str(exc))
        else:
            st.success("Todas as usinas importadas já estão vinculadas ao GRID Engenharia.", icon=":material/check_circle:")

    if mappings:
        linked_df = pd.DataFrame(mappings).rename(columns={
            "client_name": "Cliente",
            "plant_name": "Usina local",
            "provider": "Portal",
            "remote_name": "Usina remota",
            "remote_plant_id": "ID remoto",
            "last_sync_at": "Última sincronização",
            "last_sync_status": "Resultado",
            "last_error": "Erro",
        })[["Cliente", "Usina local", "Portal", "Usina remota", "ID remoto", "Última sincronização", "Resultado", "Erro"]]
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
            """SELECT reading_date AS "Data", generation_kwh AS "Geração",
                      peak_power_kw AS "Pico de potência", alarms_count AS "Alarmes", source AS "Fonte"
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
        """SELECT l.started_at AS "Início", l.finished_at AS "Término",
                  c.name AS "Cliente", p.name AS "Usina", mi.provider AS "Portal",
                  l.reference_month AS "Mês", l.status AS "Resultado",
                  l.records_received AS "Registros", l.generation_kwh AS "Geração",
                  l.message AS "Mensagem"
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

st.caption(
    "Segurança: as credenciais são criptografadas com a chave protegida do ambiente e nunca são incluídas "
    "em exportações, tabelas ou relatórios de clientes."
)
