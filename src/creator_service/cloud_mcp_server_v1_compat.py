from __future__ import annotations

import os
from typing import Any

from mcp.types import CallToolResult, ToolAnnotations

from . import cloud_mcp_server as base
from . import cloud_mcp_server_management as management
from . import cloud_mcp_server_responsible as responsible


HANDOFF_UI_URI = responsible.HANDOFF_UI_URI


def _legacy_v1_video_read(video_id: str) -> dict[str, Any]:
    """Read video details + transcript through the historical V1 preview tool.

    Frozen ChatGPT V1 snapshots know ``preview_video_metadata_update`` but do not
    know the newer dedicated ``get_video_details`` / ``get_video_transcript``
    tools. Calling that historical tool with only ``video_id`` is therefore a
    strictly read-only compatibility mode. Supplying any metadata field keeps
    the existing preview/handoff behaviour unchanged.
    """
    base._require_scope(base.READ_SCOPE)
    base._limit("legacy_v1_video_read", limit=60)
    service = responsible._service()
    details = management._owned_video_details(service, video_id)
    transcript = management.get_video_transcript_data(
        service,
        details["video_id"],
        include_segments=True,
        segment_offset=0,
        segment_limit=500,
    )
    return base.success_response(
        {
            "compatibility_mode": "v1_video_details_and_transcript",
            "read_only": True,
            "video_id": details["video_id"],
            "video": details,
            "transcript": {"title": details.get("title", ""), **transcript},
            "changed_fields": [],
            "requires_user_click": False,
            "handoff_fallback_supported": False,
            "message": (
                "Leitura compatível com o snapshot V1: detalhes e transcrição retornados sem "
                "prévia de escrita, handoff ou alteração no YouTube."
            ),
        }
    )


def _tool_meta() -> dict[str, Any]:
    public_origin = os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip().rstrip("/")
    meta: dict[str, Any] = {
        "ui": {"resourceUri": HANDOFF_UI_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": HANDOFF_UI_URI,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": "Lendo vídeo ou preparando prévia segura…",
        "openai/toolInvocation/invoked": "Leitura ou prévia concluída",
    }
    if public_origin:
        meta["openai/widgetDomain"] = public_origin
    return meta


def create_server():
    # The responsible factory now owns the exact 47-tool + 1-resource production
    # composition and fails fast if that contract drifts. V1 compatibility only
    # replaces the historical preview implementation without re-extending tools.
    server = responsible.create_server()

    # Replace only the historical tool. The name and argument schema remain
    # byte-for-byte compatible from the client's point of view: video_id,
    # title, description and tags.
    server.remove_tool("preview_video_metadata_update")

    @server.tool(
        name="preview_video_metadata_update",
        title="Ler vídeo ou pré-visualizar metadados com segurança",
        description=(
            "Read-only compatibility bridge for frozen ChatGPT V1 snapshots. "
            "When called with only video_id, returns authenticated video details and the full owner-authorized transcript. "
            "When title, description or tags are supplied, preserves the existing read-only metadata preview and one-click handoff behaviour."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
        ),
        meta=_tool_meta(),
        structured_output=False,
    )
    def preview_video_metadata_update(
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> CallToolResult:
        read_only_compat = title is None and description is None and tags is None
        if read_only_compat:
            result = base._structured(
                "preview_video_metadata_update",
                lambda: _legacy_v1_video_read(video_id),
            )
        else:
            result = base._structured(
                "preview_video_metadata_update",
                lambda: responsible._preview_metadata_with_handoff(
                    video_id=video_id,
                    title=title,
                    description=description,
                    tags=tags,
                ),
            )
        return responsible._call_result(result)

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
