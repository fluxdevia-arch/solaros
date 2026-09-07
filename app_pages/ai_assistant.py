from __future__ import annotations

import streamlit as st

from solar_crm.ai_assistant import (
    AssistantError,
    ask_assistant,
    assistant_api_key,
    assistant_model,
    assistant_provider,
    prepare_attachment,
)
from solar_crm.ui import page_intro


page_intro(
    "Converse sobre usinas, planilhas, relatórios, datasheets e fotos de campo com apoio de inteligência artificial."
)

provider = assistant_provider()
api_key = assistant_api_key(provider)
model = assistant_model(provider)
provider_label = "Gemini" if provider == "gemini" else "OpenAI"
st.session_state.setdefault("ai_messages", [])
st.session_state.setdefault("ai_attachments", [])
st.session_state.setdefault("ai_usage", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
st.session_state.setdefault("ai_connection_verified", False)

with st.container(horizontal=True, vertical_alignment="center"):
    if api_key and st.session_state.ai_connection_verified:
        st.success(f"Assistente conectado ao {provider_label} · modelo {model}", icon=":material/cloud_done:")
    elif api_key:
        st.info(f"Chave do {provider_label} configurada · conexão aguardando validação", icon=":material/key:")
    else:
        st.warning("Assistente preparado, aguardando a chave da API.", icon=":material/key:")
    if st.button("Nova conversa", icon=":material/refresh:", key="ai_new_conversation"):
        st.session_state.ai_messages = []
        st.session_state.ai_attachments = []
        st.session_state.ai_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        st.rerun()

if not api_key:
    with st.container(border=True):
        st.subheader("Ativação necessária", icon=":material/settings:")
        if provider == "gemini":
            st.write(
                "Crie gratuitamente uma chave no Google AI Studio e adicione o segredo abaixo nas "
                "configurações do aplicativo no Streamlit Cloud. Não é necessário cadastrar cartão para começar."
            )
            st.code('[gemini]\napi_key = "sua-chave-aqui"\nmodel = "gemini-3.7-flash"', language="toml")
            st.link_button(
                "Criar chave gratuita no Google AI Studio",
                "https://aistudio.google.com/app/apikey",
                icon=":material/open_in_new:",
            )
            st.caption("A camada gratuita possui limites de uso. Ao atingir a cota, o SolarOS aguardará a renovação sem cobrar automaticamente.")
            st.warning(
                "Na camada gratuita, remova CPF, documentos pessoais, senhas e outros dados sensíveis antes de enviar arquivos.",
                icon=":material/privacy_tip:",
            )
        else:
            st.write("Adicione a chave da OpenAI nas configurações do aplicativo no Streamlit Cloud.")
            st.code('[openai]\napi_key = "sua-chave-aqui"\nmodel = "gpt-5-mini"', language="toml")
            st.link_button("Criar chave na OpenAI", "https://platform.openai.com/api-keys", icon=":material/open_in_new:")
        st.caption("A chave fica no servidor e não é exibida no navegador nem salva no banco de clientes.")

if not st.session_state.ai_messages:
    with st.container(border=True):
        st.subheader("O que você pode enviar", icon=":material/attach_file:")
        st.markdown(
            """
            - Excel de geração diária ou mensal e outros arquivos CSV/XLSX
            - Faturas, relatórios, contratos e datasheets em PDF, DOCX ou texto
            - Fotos de módulos, inversores, quadros, cabos, conectores, estruturas e padrões
            """
        )
        st.caption(
            "A análise por foto é uma triagem. Confirme qualquer hipótese com medições, datasheet, normas aplicáveis e inspeção segura em campo."
        )

for message in st.session_state.ai_messages:
    with st.chat_message(message["role"], avatar=":material/solar_power:" if message["role"] == "assistant" else None):
        for attachment in message.get("attachments", []):
            if attachment.get("kind") == "image" and attachment.get("preview"):
                st.image(attachment["preview"], caption=attachment["name"], width=420)
            else:
                st.caption(f":material/attach_file: {attachment['name']}")
        st.markdown(message["content"])

submission = st.chat_input(
    "Pergunte ou anexe planilha, documento ou foto",
    key="solaros_ai_chat",
    accept_file="multiple",
    file_type=["xlsx", "csv", "pdf", "docx", "txt", "md", "jpg", "jpeg", "png", "webp"],
    max_upload_size=12,
    disabled=not bool(api_key),
    submit_mode="disable",
)

if submission:
    prompt = submission.text.strip()
    prepared = []
    errors = []
    for uploaded in submission.files:
        try:
            prepared.append(prepare_attachment(uploaded.name, uploaded.type or "application/octet-stream", uploaded.getvalue()))
        except AssistantError as exc:
            errors.append(str(exc))
    if errors:
        for error in errors:
            st.error(error, icon=":material/error:")
    if prepared or prompt:
        visible_attachments = [
            {key: value for key, value in attachment.items() if key in {"name", "kind", "preview"}}
            for attachment in prepared
        ]
        user_message = {
            "role": "user",
            "content": prompt or "Analise os arquivos anexados.",
            "attachments": visible_attachments,
        }
        st.session_state.ai_messages.append(user_message)
        st.session_state.ai_attachments.extend(prepared)
        st.session_state.ai_attachments = st.session_state.ai_attachments[-8:]

        with st.chat_message("user"):
            for attachment in visible_attachments:
                if attachment.get("kind") == "image" and attachment.get("preview"):
                    st.image(attachment["preview"], caption=attachment["name"], width=420)
                else:
                    st.caption(f":material/attach_file: {attachment['name']}")
            st.markdown(user_message["content"])

        with st.chat_message("assistant", avatar=":material/solar_power:"):
            with st.spinner("Analisando com o Assistente SolarOS..."):
                try:
                    answer, usage = ask_assistant(
                        api_key,
                        model,
                        user_message["content"],
                        st.session_state.ai_messages[:-1],
                        st.session_state.ai_attachments,
                        provider=provider,
                    )
                    st.markdown(answer)
                    st.session_state.ai_connection_verified = True
                    st.session_state.ai_messages.append({"role": "assistant", "content": answer})
                    for key in st.session_state.ai_usage:
                        st.session_state.ai_usage[key] += usage.get(key, 0)
                except AssistantError as exc:
                    st.session_state.ai_connection_verified = False
                    st.error(str(exc), icon=":material/error:")

usage = st.session_state.ai_usage
if usage.get("total_tokens"):
    st.caption(
        f"Uso desta conversa: {usage['input_tokens']:,} tokens de entrada e "
        f"{usage['output_tokens']:,} tokens de resposta."
    )
