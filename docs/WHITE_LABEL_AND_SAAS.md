# SolarOS como produto para outras empresas

## Modelo liberado agora: instalação white-label

Cada empresa deve receber uma instalação separada do SolarOS, com:

- banco PostgreSQL/Supabase próprio;
- aplicação Streamlit própria;
- provedor de login e lista de usuários autorizados próprios;
- nome do sistema, logotipo, dados empresariais e assinatura configurados na aplicação;
- segredos e integrações separados.

Esse modelo impede que clientes de empresas diferentes compartilhem o mesmo banco e permite vender a solução com identidade visual personalizada.

## Limite atual

Uma mesma instalação ainda não deve atender várias empresas independentes. O login restringe quem entra, mas os registros de negócio pertencem a uma única empresa e não possuem isolamento por organização.

## Fase futura: SaaS multiempresa

Antes de reunir várias empresas na mesma instalação, será necessário:

1. criar organizações, membros e perfis de acesso (proprietário, administrador, técnico e consulta);
2. incluir `organization_id` em todas as tabelas de negócio e filtrar todas as consultas por organização;
3. aplicar políticas de segurança no banco, preferencialmente Row Level Security no Supabase;
4. separar arquivos, logotipos, assinaturas, tokens de integração e links públicos por organização;
5. registrar auditoria de alterações e acessos;
6. implementar convite de usuários, recuperação de conta, licenças, planos e limites de uso;
7. testar explicitamente tentativas de acesso cruzado entre empresas.

Nenhuma versão multiempresa deve ser comercializada antes de esses controles serem implementados e auditados.
