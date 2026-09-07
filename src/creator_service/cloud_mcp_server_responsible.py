from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult, TextContent, ToolAnnotations

from . import cloud_mcp_server as base
from . import cloud_mcp_server_management as management
from .handoff import build_handoff_url, seal_handoff
from .responsible_service import ResponsibleCreatorService
from .security import signer_from_env


HANDOFF_UI_URI = "ui://youtube-creator-agent/handoff-v1.html"


def _service() -> ResponsibleCreatorService:
    resolver = base._resolver()
    return ResponsibleCreatorService(resolver.resolve(base._tenant_id()))


def _playlist_owned_and_contains(service: ResponsibleCreatorService, playlist_id: str, video_id: str) -> bool:
    response = service._youtube().playlists().list(part="snippet", id=playlist_id, maxResults=1).execute()
    items = response.get("items", [])
    if not items:
        raise base.tool_error("playlist_not_found")
    owner = str((items[0].get("snippet", {}) or {}).get("channelId", "")).strip()
    if owner != service._authorized_channel_id():
        raise base.tool_error("playlist_not_owned")

    page_token = None
    inspected = 0
    while True:
        kwargs: dict[str, Any] = {
            "part": "contentDetails,snippet",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        page = service._youtube().playlistItems().list(**kwargs).execute()
        for item in page.get("items", []):
            inspected += 1
            details = item.get("contentDetails", {}) or {}
            snippet = item.get("snippet", {}) or {}
            candidate = str(details.get("videoId") or (snippet.get("resourceId", {}) or {}).get("videoId") or "")
            if candidate == video_id:
                return True
        if inspected >= 5000:
            raise base.tool_error("invalid_request", "Playlist is too large for a safe one-click membership check.")
        page_token = page.get("nextPageToken")
        if not page_token:
            return False


def _prepare_handoff(
    *,
    video_id: str,
    title: str | None,
    description: str | None,
    tags: list[str] | None,
    category_id: str | None,
    playlist_id: str | None,
) -> dict[str, Any]:
    base._require_scope(base.READ_SCOPE)
    base._limit("handoff_prepare", limit=30)
    service = _service()
    service.context.validate_youtube()
    service.memory.assert_not_recently_edited(video_id)

    current = service._current_video_snippet(video_id)
    normalized = service._normalize_metadata_payload(
        video_id=video_id,
        title=title,
        description=description,
        tags=tags,
        current=current,
    )
    normalized["categoryId"] = service._normalize_category_id(category_id, current)
    normalized["defaultLanguage"] = current.get("defaultLanguage")

    changed_fields = [
        field
        for field in ("title", "description", "tags", "categoryId")
        if service._semantic_value(field, current.get(field)) != service._semantic_value(field, normalized.get(field))
    ]

    final_playlist_id = str(playlist_id or "").strip()
    if final_playlist_id:
        already_present = _playlist_owned_and_contains(service, final_playlist_id, video_id)
        if not already_present:
            changed_fields.append("playlist")

    if not changed_fields:
        return {
            "ok": True,
            "video_id": video_id,
            "video_title": current.get("title", ""),
            "changed_fields": [],
            "no_changes": True,
            "message": "A proposta já corresponde ao estado atual do vídeo; nada precisa ser aplicado.",
        }

    channel_id = service._authorized_channel_id()
    ticket, package = seal_handoff(
        tenant_id=base._tenant_id(),
        channel_id=channel_id,
        video_id=video_id,
        baseline_digest=signer_from_env().payload_digest(current),
        proposed=normalized,
        changed_fields=changed_fields,
        playlist_id=final_playlist_id,
        source="chatgpt",
        ttl_seconds=300,
    )
    public_origin = os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip().rstrip("/")
    href = build_handoff_url(ticket, public_origin)
    return {
        "ok": True,
        "version": package.version,
        "video_id": video_id,
        "video_title": current.get("title", ""),
        "channel_id": channel_id,
        "changed_fields": changed_fields,
        "expires_in_seconds": package.expires_at - package.issued_at,
        "handoff_url": href,
        "requires_user_click": True,
        "button_label": "Enviar e aplicar mudanças",
        "cancel_label": "Cancelar",
        "message": "A proposta está pronta. A alteração real só será enviada após o usuário escolher Enviar e aplicar mudanças.",
    }


def create_server():
    # Existing MCP write tools keep their full behavior, but use the same
    # responsible executor as Gemini and handoff for verified metadata writes.
    management.VerifiedAdvancedSafeCreatorService = ResponsibleCreatorService
    server = management.create_server()

    public_origin = os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip().rstrip("/")
    resource_meta: dict[str, Any] = {
        "ui": {
            "prefersBorder": True,
            "csp": {"connectDomains": [], "resourceDomains": []},
        },
        "openai/widgetDescription": "Confirmação segura para enviar uma proposta de metadados ao YouTube Creator Agent.",
        "openai/widgetPrefersBorder": True,
    }
    if public_origin:
        resource_meta["ui"]["domain"] = public_origin
        resource_meta["openai/widgetDomain"] = public_origin
        resource_meta["openai/widgetCSP"] = {"redirect_domains": [public_origin]}

    @server.resource(
        HANDOFF_UI_URI,
        name="youtube_creator_agent_handoff",
        title="Enviar e aplicar mudanças",
        description="Inline confirmation card for safe one-click YouTube handoff.",
        mime_type="text/html;profile=mcp-app",
        meta=resource_meta,
    )
    def handoff_widget() -> str:
        return (Path(__file__).resolve().parent / "web" / "handoff_widget.html").read_text(encoding="utf-8")

    tool_meta = {
        "ui": {"resourceUri": HANDOFF_UI_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": HANDOFF_UI_URI,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": "Preparando envio seguro…",
        "openai/toolInvocation/invoked": "Alterações prontas para confirmação",
    }

    @server.tool(
        name="render_video_metadata_handoff",
        title="Preparar botão seguro para aplicar mudanças",
        description=(
            "Prepare a one-click confirmation card for a metadata proposal when direct MCP write capability is unavailable. "
            "This tool never writes to YouTube: it reads the exact authenticated target, validates the proposal, and creates a short-lived encrypted handoff package."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
        ),
        meta=tool_meta,
        structured_output=False,
    )
    def render_video_metadata_handoff(
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        category_id: str | None = None,
        playlist_id: str | None = None,
    ) -> CallToolResult:
        result = base._structured(
            "render_video_metadata_handoff",
            lambda: _prepare_handoff(
                video_id=video_id,
                title=title,
                description=description,
                tags=tags,
                category_id=category_id,
                playlist_id=playlist_id,
            ),
        )
        visible = dict(result)
        href = str(visible.get("handoff_url", ""))
        meta = None
        if href and visible.get("ok"):
            meta = {
                "yca/handoff": {
                    "href": href,
                    "video_id": visible.get("video_id"),
                    "changed_fields": visible.get("changed_fields", []),
                }
            }
        text = json.dumps(visible, ensure_ascii=False, sort_keys=True)
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structuredContent=visible,
            _meta=meta,
        )

    return server


def run() -> None:
    server = create_server()
    host = os.environ.get("YCA_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("YCA_MCP_PORT", "8000"))
    server.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
    )


if __name__ == "__main__":
    run()
