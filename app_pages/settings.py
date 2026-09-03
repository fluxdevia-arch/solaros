import streamlit as st

from solar_crm.db import clear_business_data, execute, get_db_path, query_one, using_postgres
from solar_crm.signature import normalize_signature_image
from solar_crm.ui import flash, page_intro, show_flash

page_intro("Configure a identidade dos documentos, o compartilhamento e a proteção dos dados.")
show_flash()

settings = query_one("SELECT * FROM settings WHERE id=1")

left, right = st.columns([1.15, 0.85])
with left:
    with st.container(border=True):
        st.subheader("Dados da empresa", icon=":material/business:")
        with st.form("company_settings"):
            company_name = st.text_input("Nome de exibição", value=settings["company_name"] or "")
            legal_name = st.text_input("Razão social", value=settings["legal_name"] or "")
            document = st.text_input("CNPJ/CPF", value=settings["document"] or "")
            email = st.text_input("E-mail", value=settings["email"] or "")
            phone = st.text_input("Telefone", value=settings["phone"] or "")
            address = st.text_input("Endereço", value=settings["address"] or "")
            st.subheader("Responsável técnico nos relatórios", icon=":material/draw:")
            technical_name = st.text_input("Nome do responsável", value=settings["technical_name"] or "")
            technical_title = st.text_input("Título profissional", value=settings["technical_title"] or "")
            technical_registration = st.text_input("Registro profissional", value=settings["technical_registration"] or "")
            signature_upload = st.file_uploader(
                "Assinatura manuscrita",
                type=["png", "jpg", "jpeg"],
                max_upload_size=5,
                help="Prefira uma foto nítida, com assinatura escura sobre papel branco. O SolarOS remove o fundo e recorta as margens.",
            )
            remove_signature = st.checkbox("Remover a assinatura manuscrita atual", disabled=not bool(settings["signature_image"]))
            share_base_url = st.text_input(
                "URL para compartilhar ordens de serviço",
                value=settings.get("share_base_url") or "http://localhost:8501",
                help="Em rede local, use o endereço IP do computador. Quando hospedado, informe a URL pública do SolarOS.",
            )
            footer = st.text_area("Rodapé e observação legal dos relatórios", value=settings["report_footer"] or "")
            if st.form_submit_button("Salvar configurações", type="primary", icon=":material/save:"):
                try:
                    signature_image = settings["signature_image"]
                    signature_mime = settings["signature_image_mime"]
                    if remove_signature:
                        signature_image = None
                        signature_mime = None
                    elif signature_upload is not None:
                        signature_image = normalize_signature_image(signature_upload.getvalue())
                        signature_mime = "image/png"
                    execute(
                        """UPDATE settings SET company_name=?, legal_name=?, document=?, email=?, phone=?, address=?,
                           technical_name=?, technical_title=?, technical_registration=?, signature_image=?,
                           signature_image_mime=?, share_base_url=?, report_footer=? WHERE id=1""",
                        (
                            company_name, legal_name, document, email, phone, address, technical_name,
                            technical_title, technical_registration, signature_image, signature_mime,
                            share_base_url, footer,
                        ),
                    )
                    flash("Configurações e assinatura salvas.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc), icon=":material/error:")

        if settings["signature_image"]:
            st.caption("Assinatura manuscrita atual")
            st.image(settings["signature_image"], width=320)
            st.success("A assinatura será aplicada acima da linha nos próximos relatórios.", icon=":material/verified:")
        else:
            st.info("Nenhuma assinatura manuscrita cadastrada. O relatório continuará exibindo o bloco profissional digitado.", icon=":material/draw:")

with right:
    with st.container(border=True):
        st.subheader("Banco de dados", icon=":material/database:")
        if using_postgres():
            st.success("PostgreSQL em nuvem conectado", icon=":material/cloud_done:")
            st.caption("Os dados são persistidos no Supabase e compartilhados entre todos os acessos autorizados.")
            st.info("No plano gratuito, faça exportações periódicas pelo painel do Supabase.", icon=":material/backup:")
        else:
            db_path = get_db_path()
            st.caption("Todos os dados ficam em um arquivo SQLite dentro deste projeto.")
            st.code(str(db_path), language=None)
            if db_path.exists():
                st.download_button(
                    "Baixar backup",
                    db_path.read_bytes(),
                    "backup_solaros.db",
                    "application/x-sqlite3",
                    icon=":material/download:",
                )
            st.info("Faça backup antes de atualizações importantes e armazene a cópia em local seguro.", icon=":material/verified_user:")

    with st.container(border=True):
        st.subheader("Sobre esta versão", icon=":material/info:")
        st.markdown("""
        **SolarOS v1.8**

        - CRM de clientes e usinas
        - Contratos e receita recorrente
        - Leituras, faturas e economia
        - Beneficiárias, rateio mensal e créditos em kWh
        - SolarZ como integração principal de usinas, geração e desempenho
        - Conectores diretos opcionais com Growatt OpenAPI e SolisCloud
        - Kanban comercial para leads e negociações
        - Ordens de serviço com PDF e link para a equipe de campo
        - Geração de contratos de serviço e consultoria
        - Agenda, recorrências e chamados
        - Relatórios mensais em PDF
        - Caixa e faturamento de manutenção
        - Login individual por e-mail e senha
        - PostgreSQL em nuvem com migração do banco local
        """)
        st.caption("Próximas integrações possíveis: leitura automática de faturas e envio por WhatsApp/e-mail.")

    with st.expander("Preparar base para uso real", icon=":material/delete_sweep:"):
        st.warning("Esta ação remove clientes, usinas, leituras, contratos, cobranças, atividades e ocorrências. As configurações da empresa serão preservadas.")
        confirmation = st.text_input("Digite APAGAR DEMO para confirmar", key="clear_demo_confirmation")
        if st.button("Remover dados demonstrativos", disabled=confirmation != "APAGAR DEMO", icon=":material/delete:"):
            clear_business_data()
            st.session_state.selected_client_id = None
            st.session_state.selected_plant_id = None
            flash("Base demonstrativa removida. O sistema está pronto para seus dados reais.")
            st.rerun()
