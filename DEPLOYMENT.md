# Hospedagem gratuita do SolarOS

Arquitetura preparada:

- **Aplicação:** Streamlit Community Cloud.
- **Login:** Auth0 Universal Login por e-mail e senha (OIDC).
- **Banco:** PostgreSQL do Supabase.

O código continua funcionando localmente com SQLite. Quando a seção `[database]`
é configurada nos segredos, ele cria e usa automaticamente o banco PostgreSQL.

## 1. Criar o banco no Supabase

1. Crie uma conta gratuita em <https://supabase.com> e um projeto chamado `solaros`.
2. Em **Connect**, selecione a conexão **Session pooler** na porta `5432`.
3. Anote host, porta e usuário exibidos na conexão.
4. Guarde a senha do banco. Ela será usada somente nos segredos do Streamlit.

O plano gratuito pode pausar projetos com pouca atividade após sete dias. O
projeto pode ser restaurado no painel do Supabase. Faça exportações periódicas,
pois backups para download não fazem parte do plano gratuito.

## 2. Criar o login no Auth0

1. Crie uma conta gratuita em <https://auth0.com>.
2. Em **Applications > Applications**, crie `SolarOS` como **Regular Web Application**.
3. Crie o primeiro usuário em **User Management > Users** com seu e-mail e senha.
4. Em **Authentication > Database**, abra a conexão usada pela aplicação e
   desative cadastro público (**Disable Sign Ups**). Novos usuários ficam sob seu controle.
5. Na aplicação, configure:
   - **Allowed Callback URLs:** `https://SEU-APP.streamlit.app/oauth2callback`
   - **Allowed Logout URLs:** `https://SEU-APP.streamlit.app`
   - Para teste local, acrescente também `http://localhost:8501/oauth2callback`
     e `http://localhost:8501`.
6. Copie **Domain**, **Client ID** e **Client Secret**.

O `server_metadata_url` será:
`https://SEU-DOMINIO-DO-AUTH0/.well-known/openid-configuration`.

## 3. Publicar o código no GitHub

No plano gratuito atual do Streamlit Community Cloud, o repositório da aplicação
precisa ser público. Não inclua `.streamlit/secrets.toml`, arquivos `.db`, PDFs,
assinaturas ou chaves. O `.gitignore` do projeto já protege esses arquivos.

## 4. Implantar no Streamlit Community Cloud

1. Acesse <https://share.streamlit.io> e conecte sua conta GitHub.
2. Clique em **Create app**, escolha o repositório e indique `streamlit_app.py`.
3. Em **Advanced settings > Secrets**, copie o conteúdo de
   `.streamlit/secrets.toml.example` e substitua todos os valores de exemplo.
4. Gere os dois segredos locais:

   ```powershell
   .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
   .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   O primeiro é `cookie_secret`; o segundo é `solaros_encryption_key`.
5. Em `solaros_allowed_emails`, liste apenas as contas autorizadas.
6. Faça o deploy. No primeiro acesso, o SolarOS cria as tabelas em branco.

## 5. Levar os dados atuais para a nuvem

Depois de configurar `DATABASE_URL` e `SOLAROS_ENCRYPTION_KEY` como variáveis de
ambiente no computador, execute uma vez:

```powershell
$env:DATABASE_URL="SUA_URI_DO_SUPABASE"
$env:SOLAROS_ENCRYPTION_KEY="SUA_CHAVE_FERNET"
.\.venv\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py
```

O migrador para se o banco de destino já tiver dados empresariais, evitando
sobrescrita acidental. Após a migração, remova as variáveis da sessão do terminal.

## Segurança operacional

- Nunca envie Client Secret, senha do banco ou chave Fernet por mensagem.
- Mantenha cadastro público desativado no Auth0.
- Faça exportações regulares do banco e dos relatórios.
- Links de ordem de serviço são links secretos individuais; regenere o token se
  um link for compartilhado com a pessoa errada.
