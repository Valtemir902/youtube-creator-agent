# YouTube Creator Agent Elite

Professional YouTube intelligence, SEO research, channel strategy and publishing platform.

The project now uses a shared service architecture so the same intelligence can be consumed by:

- the PySide6 desktop app;
- a future authenticated cloud backend;
- ChatGPT/Codex through Model Context Protocol (MCP).

## Current capabilities

- Multi-AI runtime: Gemini, OpenAI, Groq, xAI/Grok, Ollama and OpenAI-compatible endpoints
- Dynamic model discovery per provider/account
- YouTube OAuth integration
- YouTube Analytics channel learning
- Real search-term signals from the connected channel
- Keyword opportunity scoring based on measurable YouTube evidence
- Channel-specific fit scoring
- Shorts vs long-form analysis
- 7-day editorial strategy
- Opportunity momentum/history
- Post-action observation without claiming false causality
- Evidence-first channel audit
- YouTube video metadata review/update
- Optional TikTok publishing support
- MCP tools for ChatGPT integration

## Desktop

Create and activate a Python virtual environment, install `requirements.txt`, configure Google OAuth and your AI provider, then run:

```bash
python main.py
```

`main.py` is the supported desktop entrypoint. Legacy UI modules remain only while migration is completed.

## MCP server

The MCP layer exposes the same application service used by the desktop instead of duplicating business logic.

Install the desktop dependencies plus the server dependencies:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-server.txt
```

Set an approval signing secret before enabling write tools:

```text
YCA_APPROVAL_SECRET=<random secret with at least 24 characters>
```

Optional server settings:

```text
YCA_MCP_HOST=127.0.0.1
YCA_MCP_PORT=8000
YCA_ROOT=<project root>
```

Start the MCP server:

```bash
python mcp_server.py
```

Default endpoint:

```text
http://127.0.0.1:8000/mcp
```

### MCP tools

Read-only tools:

- `creator_status`
- `get_channel_profile`
- `research_youtube_topic`
- `build_channel_strategy`

Write flow:

1. `preview_video_metadata_update` reads the current metadata and returns the exact proposed change.
2. The server signs the target, baseline and proposed payload with an expiring HMAC approval token.
3. The user must explicitly approve the preview.
4. `apply_video_metadata_update` verifies the signature, expiry, exact payload and that the video did not change since preview.
5. Only then is the YouTube update executed.

This prevents a model or stale client from silently modifying a different payload than the one the user reviewed.

## Architecture

```text
Desktop UI ──────────────┐
                         │
ChatGPT / MCP ── MCP ────┼── CreatorService ── Intelligence Engines ── YouTube APIs
                         │
Future Web/API ──────────┘                  └── Multi-AI Runtime
```

The current MCP resolver is intentionally local/single-tenant. Production multi-user distribution will replace it with authenticated account resolution and encrypted per-user OAuth storage without changing the intelligence layer.

## Security

Never commit:

- `config/.env`
- Google OAuth client secrets
- YouTube/TikTok tokens
- API keys
- local SQLite databases
- build output or virtual environments

Write operations are intentionally separated from read operations and require explicit approval.

See `config/README.md` for local credential setup.
