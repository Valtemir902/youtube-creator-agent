# Production Deployment Runbook

## Services

The cloud product uses two HTTP services from the same server image:

1. **MCP** — `python cloud_mcp_server.py`, default port 8000, public MCP path `/mcp`.
2. **Onboarding** — `python onboarding_server.py`, default port 8080, web setup/API plus `/health` and `/ready`.

Use separate public hostnames or reverse-proxy routes. TLS should terminate at a trusted edge/reverse proxy and the public URLs configured in environment variables must be HTTPS.

## Build

```bash
docker build -f Dockerfile.server -t youtube-creator-agent-server .
```

The server image intentionally installs `requirements-server.txt`, not desktop GUI/Whisper/Torch dependencies.

## Required secrets

Store these only in the hosting platform secret manager:

- `YCA_APPROVAL_SECRET`
- `YCA_DATA_ENCRYPTION_KEY`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `YCA_AUTH_INTROSPECTION_CLIENT_SECRET`

Do not place production values in `config/server.env` inside Git.

## Required public configuration

Set all values documented in `config/server.env.example`, especially:

- `YCA_APP_PUBLIC_URL`
- `YCA_MCP_PUBLIC_URL`
- `YCA_ONBOARDING_PUBLIC_URL`
- `YCA_PRIVACY_URL`
- `YCA_TERMS_URL`
- `YCA_SUPPORT_URL`
- `YCA_AUTH_ISSUER_URL`
- `YCA_AUTH_INTROSPECTION_URL`
- `GOOGLE_OAUTH_REDIRECT_URI`

## Storage

The current cloud implementation uses SQLite for encrypted tenant state, onboarding sessions, rate-limit windows and audit events.

Recommended small/single-host deployment:

- persistent local/block volume;
- encrypted volume/backups;
- one logical writer host;
- MCP and onboarding processes may share the same database file on that host.

Before horizontal multi-host scaling, migrate storage interfaces to a network database such as a managed SQL service. Do not place SQLite on an eventually-consistent object store or a multi-host network filesystem that does not provide SQLite-compatible locking semantics.

## Reverse proxy

Forward the real HTTPS public origins to the internal service ports. Preserve request IDs where possible. Do not expose internal database or debug ports.

If a proxy supplies forwarded client IP headers, configure the ASGI server's trusted forwarded IP list narrowly. Do not trust arbitrary internet clients to set their own forwarded identity headers.

## Health and readiness

Liveness:

```text
GET /health
```

Expected: HTTP 200 whenever the onboarding process is running.

Production readiness:

```text
GET /ready
```

Expected before release: HTTP 200 and:

```json
{"ready": true, "checks": {"...": true}, "missing": []}
```

A 503 response is intentional when required production URLs/secrets are missing.

## Logs and audit

HTTP request logs are JSON lines containing request ID, method, path, status and elapsed milliseconds.

Audit events store sanitized operational metadata. The sanitizer redacts fields whose names contain token/secret/password/api_key/authorization/cookie. Do not add raw request bodies to audit metadata.

Production operations should define:

- log retention;
- who can access logs;
- alerting for sustained 5xx/429 rates;
- backup schedule and restore test;
- secret rotation procedure;
- incident contact.

## Rate limits

Current per-tenant guardrails are intentionally stricter for costly or mutating operations than for lightweight reads. They protect YouTube/API quota and reduce accidental tool loops.

For large-scale deployments, move rate-limit counters to a shared network store so limits remain consistent across replicas.

## Release sequence

1. Deploy to staging with test OAuth credentials.
2. Run CI and MCP contract tests.
3. Verify `/health`.
4. Verify `/ready` after staging values are populated.
5. Test one-time onboarding link reuse rejection.
6. Connect a test YouTube channel.
7. Exercise read-only MCP tools.
8. Exercise preview flow.
9. Deny a write and verify no mutation.
10. Approve a controlled test write and verify audit event.
11. Rotate/revoke the test connection.
12. Publish final Privacy/Terms/support pages.
13. Deploy production secrets and URLs.
14. Verify production `/ready` returns 200.
15. Test as a ChatGPT draft app before submission.
