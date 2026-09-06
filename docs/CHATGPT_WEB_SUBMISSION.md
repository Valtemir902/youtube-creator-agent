# YouTube Creator Agent — ChatGPT Web / Plugin Directory

This document records the production path for making YouTube Creator Agent usable from normal ChatGPT conversations, not only Codex/desktop.

## Current diagnosis

The packaged plugin in `plugins/youtube-creator-agent/` declares a remote MCP server through `.mcp.json`. Imported plugins that declare MCP this way can be classified as desktop-only, even when the MCP URL is public HTTPS.

That does **not** mean the MCP backend is wrong. The production MCP endpoint is:

```text
https://mcp.silvadigitaltech.com/mcp
```

The public ChatGPT path is to submit/register the MCP-backed app through OpenAI's app/plugin submission flow and then distribute it through the Plugin Directory. For public submission, use the production MCP URL itself rather than a machine-specific ChatGPT app/connector ID.

## Public submission target

Submission mode: **With MCP**

Production MCP URL:

```text
https://mcp.silvadigitaltech.com/mcp
```

Do not submit localhost URLs, tunnel URLs, secrets, bearer tokens, or a development-only `plugin_asdk_app_*` ID.

## Packaged plugin behavior

The repository keeps `.mcp.json` so Codex/desktop can continue using the remote MCP directly.

A local `.app.json` reference is only useful after a ChatGPT app/connection has been registered and a technical app ID exists. Such IDs are environment/account specific and should not be committed as the public distribution mechanism.

If local testing needs a registered app reference, create an uncommitted `.app.json` at the plugin root using this shape:

```json
{
  "apps": {
    "youtube-creator-agent": {
      "id": "plugin_asdk_app_<registered-id>"
    }
  }
}
```

and temporarily add this field to `.codex-plugin/plugin.json`:

```json
"apps": "./.app.json"
```

Do not commit a personal/development app ID unless the release process explicitly requires a stable public app ID.

## Release checks before submission

1. `https://mcp.silvadigitaltech.com/mcp` is reachable over HTTPS.
2. Production OAuth is configured and no secrets are present in Git.
3. `GET /health` returns 200.
4. `GET /ready` returns 200 with no missing production requirements.
5. Read tools work for an authenticated YouTube account.
6. Write tools require the expected preview/approval/confirmation flow.
7. Privacy, Terms and support URLs are public and accurate.
8. Tool names/descriptions clearly distinguish read-only actions from modifying actions.
9. Submission screenshots/listing copy describe ChatGPT and Codex, not Codex only.

## Expected result

After OpenAI accepts/publishes the MCP-backed app/plugin, eligible users can install/connect it from the Plugin Directory and invoke it in normal ChatGPT conversations using the plugin/app controls available to their account. Availability still depends on plan, region, product surface and app capabilities.
