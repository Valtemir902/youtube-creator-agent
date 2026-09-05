# YouTube Creator Agent — ChatGPT App Publication Checklist

This checklist is the release gate for the public ChatGPT app/plugin path. It intentionally separates code-complete from publish-ready.

## 1. Product identity

- [ ] Confirm final public name: `YouTube Creator Agent`.
- [ ] Prepare square logo and store artwork outside the secrets repository.
- [ ] Confirm public short and long descriptions.
- [ ] Confirm support contact and support URL.
- [ ] Confirm legal business/operator name used in Terms and Privacy Policy.
- [ ] Replace every `SEU-DOMINIO` placeholder in `config/chatgpt_app.example.json`.

## 2. Public HTTPS endpoints

Production readiness requires all of these to use HTTPS:

- [ ] `YCA_APP_PUBLIC_URL`
- [ ] `YCA_MCP_PUBLIC_URL`
- [ ] `YCA_ONBOARDING_PUBLIC_URL`
- [ ] `YCA_PRIVACY_URL`
- [ ] `YCA_TERMS_URL`
- [ ] `YCA_SUPPORT_URL`
- [ ] `YCA_AUTH_ISSUER_URL`
- [ ] `YCA_AUTH_INTROSPECTION_URL`
- [ ] `GOOGLE_OAUTH_REDIRECT_URI`

`GET /ready` must return HTTP 200 before a production submission. HTTP 503 means configuration is incomplete.

## 3. OAuth and account isolation

- [ ] OAuth/OIDC provider is production configured.
- [ ] MCP derives tenant identity from the authenticated access token, never from model input.
- [ ] `yca:read` and `yca:write` scopes are independently enforced.
- [ ] Google OAuth is configured as a web application for each customer's own YouTube account.
- [ ] OAuth callback domain is verified and matches the deployed URL.
- [ ] Revocation/disconnect flow is tested.
- [ ] Customer A cannot read, modify or decrypt Customer B data.

## 4. ChatGPT Native contract

The cloud MCP must keep ChatGPT as the LLM/intelligence layer.

- [ ] No backend LLM call is required for `get_channel_profile`.
- [ ] No backend LLM call is required for `get_strategy_evidence`.
- [ ] No backend LLM call is required for `validate_keyword_candidates`.
- [ ] External Gemini/OpenAI/Groq/xAI/Ollama configuration remains optional for ChatGPT Native mode.
- [ ] `demand_index` is never described as exact daily/monthly search volume.
- [ ] Other authorized ChatGPT apps may be combined by ChatGPT, but this app never assumes another app is installed.

## 5. Tool safety and permissions

Read-only tools:

- `creator_status`
- `get_creator_capabilities`
- `create_onboarding_link` (creates only a short-lived setup link)
- `get_channel_profile`
- `get_strategy_evidence`
- `validate_keyword_candidates`

Write workflow:

1. `preview_video_metadata_update` reads current metadata and creates a signed preview.
2. User reviews the exact proposed title/description/tags.
3. `apply_video_metadata_update` requires `yca:write`, a valid signed payload and explicit confirmation.
4. Server rejects expired/tampered previews and stale baselines.

Release tests:

- [ ] Write action without explicit confirmation is rejected.
- [ ] Expired approval token is rejected.
- [ ] Modified approval payload is rejected.
- [ ] Video changed after preview forces a new preview.
- [ ] Read-only access cannot invoke the write flow successfully.

## 6. Abuse protection and operational safety

- [ ] Per-tenant rate limiting enabled.
- [ ] Onboarding link creation rate limited.
- [ ] Keyword research has a stricter quota than lightweight reads.
- [ ] Structured request logs enabled.
- [ ] Audit events contain no access tokens, cookies, API keys or OAuth secrets.
- [ ] Production logs have retention and access controls defined by the hosting provider.
- [ ] Database backups are encrypted and restore-tested.
- [ ] `YCA_DATA_ENCRYPTION_KEY` and `YCA_APPROVAL_SECRET` live only in the hosting secret manager.

## 7. Privacy and Terms

OpenAI's app directory surfaces an app's Terms and Privacy Policy before/while users enable the app, so these must be real public documents, not placeholders.

- [ ] Review `docs/PRIVACY_POLICY_TEMPLATE.md` with a qualified reviewer and publish the final policy.
- [ ] Review `docs/TERMS_TEMPLATE.md` with a qualified reviewer and publish the final terms.
- [ ] State what YouTube/Google data is accessed.
- [ ] State what credentials/tokens are stored and how they are protected.
- [ ] State retention/deletion behavior.
- [ ] State how a user disconnects YouTube and requests account/data deletion.
- [ ] State third-party processors/hosting actually used in production.
- [ ] Do not claim a processor, retention period or legal basis that has not been implemented.

## 8. Deployment gate

- [ ] Build server image from `Dockerfile.server`.
- [ ] Run unit tests and MCP contract CI.
- [ ] Verify `/health` returns 200.
- [ ] Verify `/ready` returns 200 with zero missing checks.
- [ ] Verify OAuth from a clean browser session.
- [ ] Verify onboarding one-time link cannot be reused.
- [ ] Verify MCP from a ChatGPT draft app in developer mode.
- [ ] Test read-only prompt set.
- [ ] Test write/confirmation prompt set.
- [ ] Test cancellation/denial of write.
- [ ] Test multi-app use when another authorized app is present, without creating a hard dependency.

## 9. ChatGPT submission

At the time this checklist was written, OpenAI supports custom MCP apps for testing in developer mode and developers can submit apps for review/publication. Availability and write-action support can vary by plan and workspace.

Before submission:

- [ ] Re-check current OpenAI Apps/Plugins submission documentation because product requirements can change.
- [ ] Ensure app name, logo, descriptions, Terms, Privacy Policy and connection requirements match the deployed product.
- [ ] Ensure every exposed action description accurately states read/write behavior.
- [ ] Verify all warnings/approvals shown by ChatGPT make sense for metadata-changing actions.
- [ ] Submit only the production MCP URL, never localhost/tunnel-development URLs.

## 10. Definition of done

The app is publish-ready only when:

1. CI is green.
2. `/ready` is green in production.
3. OAuth and tenant isolation are tested end to end.
4. Legal/support URLs are live.
5. ChatGPT developer-mode testing passes both read and write scenarios.
6. No production secret exists in Git.
