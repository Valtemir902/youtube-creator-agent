# YouTube Creator Agent — ChatGPT App Submission Package

Use this document as the source of truth when filling the ChatGPT app/plugin submission form.

## Identity

**App name:** YouTube Creator Agent

**Developer:** Silva Digital Tech

**Category:** Productivity

**Short description:**

Analisa dados reais do YouTube, valida oportunidades e aplica alterações aprovadas no canal.

**Long description:**

Use o ChatGPT como cérebro estratégico e o YouTube Creator Agent como camada autenticada de dados e ações. O app consulta YouTube Data API e YouTube Analytics, valida oportunidades com métricas observáveis, fornece evidências para estratégia e só aplica alterações de título, descrição e tags após prévia assinada e confirmação explícita do usuário.

## Production endpoints

**Submission type:** With MCP

**MCP URL:**

```text
https://mcp.silvadigitaltech.com/mcp
```

**App/onboarding origin:**

```text
https://creator.silvadigitaltech.com
```

**Health:**

```text
https://creator.silvadigitaltech.com/health
```

**Readiness:**

```text
https://creator.silvadigitaltech.com/ready
```

**Onboarding:**

```text
https://creator.silvadigitaltech.com/onboarding
```

**Privacy:**

```text
https://creator.silvadigitaltech.com/privacy
```

**Terms:**

```text
https://creator.silvadigitaltech.com/terms
```

**Support:**

```text
https://creator.silvadigitaltech.com/support
```

## Authentication and scopes

Authentication: OAuth/OIDC bearer tokens.

Scopes:

- `yca:read` — leitura de status, perfil, Analytics, evidências e validação de oportunidades.
- `yca:write` — criação de prévia e aplicação de alterações explicitamente aprovadas.

The MCP derives tenant identity from authenticated token claims. `tenant_id` is never accepted as model input.

## Exposed ChatGPT-native tools

Read/configuration tools:

- `creator_status`
- `get_creator_capabilities`
- `create_onboarding_link`
- `get_channel_profile`
- `get_strategy_evidence`
- `validate_keyword_candidates`

Write workflow:

- `preview_video_metadata_update`
- `apply_video_metadata_update`

`apply_video_metadata_update` requires `yca:write`, an unchanged baseline, a valid signed approval package and explicit user confirmation.

## Safety claims

- Read tools do not modify YouTube.
- Write actions are separated from reads.
- Metadata writes require an exact preview before application.
- Expired or tampered approval packages are rejected.
- A video changed after preview requires a new preview.
- Arbitrary keyword search volume is not claimed as exact YouTube search volume.
- ChatGPT-native mode does not require an external backend LLM.
- Secrets and OAuth tokens are not stored in the public Git repository.

## Suggested starter prompts

1. Verifique o status do meu canal no YouTube e resuma o que precisa da minha atenção.
2. Analise as evidências dos últimos 28 dias e identifique os temas e formatos com maior potencial para o meu canal.
3. Valide estas ideias de palavras-chave usando os dados reais disponíveis do meu canal.
4. Crie uma prévia segura para melhorar o título, a descrição e as tags deste vídeo. Não aplique nada sem minha confirmação.

## Review test cases

### Read-only

Prompt: `Verifique o status do meu canal.`

Expected: uses `creator_status`; no write action occurs.

Prompt: `Analise meu desempenho dos últimos 28 dias.`

Expected: uses profile/evidence tools and returns grounded channel analysis without invoking a backend LLM.

### Write preview

Prompt: `Prepare um novo título e descrição para este vídeo, mas não altere o canal ainda.`

Expected: ChatGPT creates candidates and calls `preview_video_metadata_update`; no YouTube mutation occurs.

### Write apply

Prompt after reviewing the exact preview: `Confirmo. Pode aplicar exatamente essa alteração.`

Expected: `apply_video_metadata_update` is invoked with the unchanged signed package and explicit confirmation.

### Safety rejection

Expected failures:

- apply without explicit confirmation;
- apply with expired approval token;
- apply with modified signed payload;
- apply after the source video metadata changed;
- write with read-only authorization.

## Verified production checks

The repository contains a GitHub Actions workflow at `.github/workflows/production-readiness.yml` that checks the production URLs. A successful run verifies:

- onboarding `/health` returns success;
- publication `/ready` returns success;
- Privacy, Terms and Support pages are reachable;
- onboarding route is reachable;
- public MCP route exists and returns either a valid response or an expected authentication response.

Before final submission, confirm the latest Production Readiness and normal CI runs are green.

## Submission notes

Submit the production MCP URL, not a localhost/tunnel URL and not a personal `plugin_asdk_app_*` identifier. Keep the existing packaged Codex plugin for desktop/Codex use; public ChatGPT distribution should be tied to the production MCP-backed app review and publication flow.
