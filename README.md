# SolarOS

Sistema profissional para estruturar o pós-venda e o pré-dimensionamento de projetos de energia solar. O SolarOS reúne clientes, usinas, contratos recorrentes, leituras mensais, faturas, economia, atividades, manutenções, chamados e relatórios em PDF.

## O que já está pronto

- Painel executivo com clientes, usinas, potência, MRR, geração, economia e pendências.
- Cadastro e atualização de clientes, usinas e contratos.
- Formação de preço por parcela base, quantidade de usinas, potência e adicionais.
- Controle de mensalidades do pós-venda.
- Leituras mensais manuais ou por importação CSV.
- Cadastro ilimitado de UCs beneficiárias por usina, com percentual de rateio, energia destinada, compensação e saldo de créditos em kWh.
- SolarZ como integração principal, com credenciais protegidas pelo Windows, importação de usinas, geração diária e desempenho mensal.
- Conectores diretos opcionais com Growatt OpenAPI e SolisCloud.
- Kanban comercial com etapas, valor do funil, probabilidade, responsável e próxima ação.
- Ordens de serviço com endereço, contato, instruções, materiais, PDF e link individual para a equipe de campo.
- Atualização da O.S. pelo técnico e possibilidade de invalidar o link anterior.
- Vistorias técnicas mobile-first, vinculadas a cliente, usina e ordem de serviço, com link individual para a equipe de campo.
- Checklist elétrico e fotovoltaico, posição solar, sombreamento, coordenadas, medições CC/CA, aterramento, diagnóstico, retorno e até 20 fotos por vistoria.
- Relatório fotográfico de vistoria em PDF com identidade visual configurável, resultados destacados e assinatura técnica padronizada.
- Gerador de contratos para pós-venda, manutenção, consultoria e projetos, com histórico e PDF.
- Cálculo de cobertura, desempenho, disponibilidade e economia estimada.
- Agenda de limpeza, prevenção, relacionamento e relatórios recorrentes.
- Chamados com severidade, SLA, causa raiz e solução.
- Demonstrativo PDF por cliente e mês, pronto para download.
- Banco SQLite local ou PostgreSQL em nuvem e download de backup local.
- Login individual por e-mail e senha usando autenticação OIDC, com lista de usuários autorizados.
- Área de engenharia para pré-dimensionar sistema FV, strings, inversor, cabos CC/CA, disjuntores e eletrodutos.
- Catálogo técnico de módulos e inversores com anexo dos datasheets e leitura local assistida de parâmetros em PDFs textuais.
- Projeto fotovoltaico completo com distribuição balanceada por strings/MPPT, cabos CC e CA, fusível gPV, seccionamento, DPS e croqui sobre foto da cobertura.
- Propostas comerciais em PDF para consultoria, projeto, manutenção e pós-venda, com histórico, status, assinatura técnica e identidade visual configurável.
- Consulta guiada ao padrão de entrada residencial da Energisa PB, com referência às tabelas da NDU 001.
- Memorial de pré-dimensionamento para download.
- Caixa gerencial com receitas, despesas, faturamento de manutenção, contas a receber/pagar, fluxo mensal e edição dos lançamentos.
- Lançamento automático no caixa de consultorias, contratos de serviço, cobranças e primeira mensalidade dos novos contratos recorrentes.
- Assinatura do responsável técnico e detalhamento por unidade beneficiária no relatório PDF, configuráveis no sistema.
- Upload de assinatura manuscrita em PNG/JPG, com remoção automática do fundo e posicionamento acima da linha.
- Modo white-label por instalação, com nome e logotipo próprios no login, menu e documentos.

O banco é iniciado uma única vez com dados demonstrativos para permitir avaliação imediata. Quando quiser começar a operação real, use **Configurações > Preparar base para uso real** e confirme a limpeza. Os dados de exemplo não serão recriados.

## Executar no Windows

Na pasta do projeto, use:

```powershell
.\.venv\Scripts\streamlit.exe run streamlit_app.py
```

Ou dê dois cliques em `iniciar_sistema.bat`. O iniciador agora aguarda o servidor ficar pronto antes de abrir o navegador e grava eventuais erros na pasta `logs`.

O navegador abrirá em `http://localhost:8501`.

## Instalação em outro computador

Com Python 3.11 ou mais recente:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\streamlit.exe run streamlit_app.py
```

## Hospedagem gratuita

O projeto está preparado para Streamlit Community Cloud, banco PostgreSQL do
Supabase e login por e-mail e senha do Auth0. Consulte o passo a passo completo
em [DEPLOYMENT.md](DEPLOYMENT.md). Os segredos reais nunca devem ser enviados ao
GitHub; use `.streamlit/secrets.toml.example` apenas como modelo.

Para comercializar a solução, use uma instalação e um banco separados por
empresa. O modelo atual e os requisitos de uma futura versão SaaS multiempresa
estão documentados em [docs/WHITE_LABEL_AND_SAAS.md](docs/WHITE_LABEL_AND_SAAS.md).

## Dados e backup

Os registros ficam em `data/solar_crm.db`. A tela Configurações permite baixar uma cópia do banco. Antes de usar dados reais, ajuste a identidade da sua empresa e revise os campos do relatório.

## Integração com os inversores

Na página **Integrações**, cadastre primeiro a conta SolarZ, teste a conexão e associe cada usina encontrada à usina correspondente no SolarOS.

- **SolarZ (principal):** em Configurações > Usuário de API, gere um usuário e uma senha exclusivos para integração. A senha é exibida uma única vez.
- **Growatt:** informe o API Token da conta OpenAPI.
- **SolisCloud:** informe o API ID e o API Secret liberados em API Management.
- As credenciais são criptografadas pelo Windows no modo local e por chave Fernet na nuvem; elas não aparecem em tabelas, backups CSV ou relatórios.
- A sincronização atualiza geração e desempenho, preservando consumo, tarifa e valor da fatura para conferência manual.

Para executar a sincronização por agendador do Windows, configure uma tarefa que rode na pasta do projeto:

```powershell
.\.venv\Scripts\python.exe -m scripts.sync_monitoring
```

## Links de ordem de serviço

Em **Configurações**, informe a URL usada pela equipe para acessar o SolarOS. Em rede local, use o IP do computador servidor, por exemplo `http://192.168.0.20:8501`. Se o sistema estiver hospedado, use a URL HTTPS pública.

Cada O.S. recebe um código aleatório. O link abre uma visualização de campo sem a navegação administrativa e permite registrar o andamento e a conclusão. O botão **Gerar novo link** invalida imediatamente o endereço anterior.

## Vistorias em celular e tablet

Na página **Vistorias**, crie a ficha, vincule uma O.S. quando aplicável e envie o link individual pelo WhatsApp. A ficha abre sem o menu administrativo, adapta os campos à tela do aparelho e permite fotografar com a câmera ou selecionar imagens da galeria. As fotos são reduzidas antes do armazenamento para economizar espaço no banco gratuito. Ao concluir, o relatório em PDF reúne identificação, condições do local, posição solar, medições, checklist, diagnóstico, fotos e assinaturas.

## Contratos de serviço

Os modelos do SolarOS são minutas administrativas para agilizar o preenchimento e a emissão. Antes da assinatura, revise o documento com assessoria jurídica e adapte tributos, responsabilidades, garantias e foro ao serviço contratado.

## Fluxo mensal recomendado

1. Receber as faturas e conferir o portal dos inversores.
2. Registrar ou importar as leituras de cada usina.
3. Revisar usinas abaixo de 90% de desempenho e abrir ocorrências.
4. Atualizar causas, soluções, limpezas e próximos passos.
5. Gerar o PDF do cliente e cumprir o checklist de envio.
6. Registrar a cobrança do contrato de pós-venda.

## Testes

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
