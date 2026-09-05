# YouTube Creator Agent

Professional YouTube intelligence, channel strategy and safe publishing platform for desktop and ChatGPT.

## Product modes

### ChatGPT Native

ChatGPT is the intelligence layer. The cloud backend supplies authenticated YouTube data, deterministic evidence and safe actions. A separate Gemini/OpenAI/Groq/xAI/Ollama key is **not required**.

Cloud MCP read tools:

- `creator_status`
- `get_creator_capabilities`
- `create_onboarding_link`
- `get_channel_profile`
- `get_strategy_evidence`
- `validate_keyword_candidates`

Write workflow:

1. `preview_video_metadata_update` reads the current video metadata and creates an exact signed preview.
2. The user reviews the proposed title, description and tags.
3. `apply_video_metadata_update` requires `yca:write`, explicit confirmation, a valid approval token and an unchanged baseline.
4. The server rejects tampered, stale or expired approval packages.

The cloud contract intentionally does **not** expose the legacy strategy tools that invoke an external backend LLM.

### Desktop / Standalone

The PySide6 desktop application can optionally use Gemini, OpenAI, Groq, xAI/Grok, Ollama or compatible endpoints.

```bash
python -m pip install -r requirements.txt
python main.py
```

## Current intelligence capabilities

- YouTube OAuth and YouTube Analytics learning
- real search terms that generated traffic for the connected channel when available from Analytics
- observable-result keyword research
- deterministic opportunity score and channel fit
- 7/30/90-day freshness signals
- competition and breakout signals
- Shorts vs long-form behavior
- strategy history and momentum
- post-action observation without false causal claims
- safe metadata preview/apply flow
- optional standalone multi-AI runtime

The public YouTube API does not expose exact arbitrary daily/monthly keyword search volume. `demand_index` is therefore an estimated evidence-based index, not a fabricated exact search count.

## Cloud services

Install only the lightweight server dependencies:

```bash
python -m pip install -r requirements-server.txt
```

Authenticated MCP server:

```bash
python cloud_mcp_server.py
```

Onboarding web/API server:

```bash
python onboarding_server.py
```

Local single-tenant MCP development server:

```bash
python mcp_server.py
```

## Secure onboarding

The cloud MCP can create a short-lived one-time onboarding link. The raw launch token is exchanged for a server-side session and removed from the URL. Browser sessions use `HttpOnly`, `Secure` cookies in production.

The onboarding panel makes the two readiness modes explicit:

- ChatGPT Native: YouTube connection is sufficient; external AI is optional.
- Standalone: YouTube plus an external/local AI provider and model are required.

## Production hardening

v13 adds:

- publication metadata/readiness validation;
- `GET /health` liveness endpoint;
- `GET /ready` production configuration gate;
- public `GET /api/app/metadata` without secrets;
- per-tenant SQLite-backed rate limiting;
- stricter limits for keyword research and write actions;
- structured JSON request logging with request IDs;
- sanitized audit events that redact secret-like fields;
- security response headers on onboarding HTTP traffic;
- lightweight server-only container image;
- app metadata, legal-policy templates and a release checklist.

`/ready` must return HTTP 200 before production submission. It checks public HTTPS URLs, authentication configuration, Google OAuth configuration and critical server secrets without returning secret values.

## Container image

Build the server image:

```bash
docker build -f Dockerfile.server -t youtube-creator-agent-server .
```

A two-service single-host example is available at:

```text
deploy/docker-compose.example.yml
```

The current SQLite storage is appropriate for a single-host deployment. Before horizontal multi-host scaling, migrate tenant/session/rate-limit/audit persistence to a network database.

## Architecture

```text
                          ┌─ Other authorized ChatGPT apps, when available
                          │
ChatGPT ── OAuth ── MCP ──┼─ YouTube Creator Agent Cloud
                          │      ├─ YouTube Data API
                          │      ├─ YouTube Analytics
                          │      ├─ deterministic evidence/scoring
                          │      └─ signed + confirmed YouTube writes
                          │
                          └─ ChatGPT performs reasoning/titles/strategy

Desktop ───────────────────── Multi-AI Runtime + same intelligence foundations
```

## Security invariants

Never commit:

- `config/.env` or populated `config/server.env`
- Google OAuth client secrets
- YouTube/TikTok access or refresh tokens
- external AI API keys
- `YCA_DATA_ENCRYPTION_KEY`
- `YCA_APPROVAL_SECRET`
- local SQLite databases
- build output or virtual environments

Cloud tenant identity comes from authenticated token claims, not from model-supplied `tenant_id`. Read and write scopes are enforced separately.

## Publication

Use these files as the release gate:

- `docs/PUBLISHING_CHECKLIST.md`
- `config/chatgpt_app.example.json`
- `docs/PRIVACY_POLICY_TEMPLATE.md`
- `docs/TERMS_TEMPLATE.md`

The templates are intentionally not final legal documents. Production Privacy/Terms/support URLs must point to reviewed, accurate public pages before submission.
