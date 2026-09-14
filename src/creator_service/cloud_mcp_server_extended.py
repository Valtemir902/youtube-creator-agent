from __future__ import annotations

import os
from typing import Any

from mcp.types import ToolAnnotations

from .advanced_service import AdvancedSafeCreatorService
from .cloud_mcp_server import (
    READ_SCOPE,
    WRITE_SCOPE,
    _audit,
    _limit,
    _require_scope,
    _resolver,
    _tenant_id,
    create_server as create_base_server,
)


def _service() -> AdvancedSafeCreatorService:
    resolver = _resolver()
    context = resolver.resolve(_tenant_id())
    return AdvancedSafeCreatorService(context)


def create_server():
    server = create_base_server()

    @server.tool(
        title="Listar categorias de vídeo do YouTube",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def list_video_categories(region_code: str = "BR") -> dict[str, Any]:
        _require_scope(READ_SCOPE)
        _limit("read", limit=180)
        return _service().list_video_categories(region_code=region_code)

    @server.tool(
        title="Preparar prévia avançada de metadados do vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_video_metadata_update_advanced(
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        category_id: str | None = None,
    ) -> dict[str, Any]:
        _require_scope(WRITE_SCOPE)
        _limit("write_preview", limit=30)
        result = _service().preview_video_metadata_update(
            video_id=video_id,
            title=title,
            description=description,
            tags=tags,
            category_id=category_id,
        )
        _audit(
            "mcp_video_metadata_preview_advanced",
            "success",
            metadata={"video_id": video_id, "changed": result.get("changed", {})},
        )
        return result

    @server.tool(
        title="Aplicar metadados avançados aprovados no vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_video_metadata_update_advanced(
        approval_payload: dict[str, Any],
        approval_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        _require_scope(WRITE_SCOPE)
        _limit("write_apply", limit=15)
        if user_confirmed is not True:
            _audit("mcp_video_metadata_apply_advanced", "denied", metadata={"reason": "confirmation_missing"})
            raise ValueError("Confirmação explícita do usuário é obrigatória.")
        result = _service().apply_video_metadata_update(
            approval_payload=approval_payload,
            approval_token=approval_token,
        )
        _audit(
            "mcp_video_metadata_apply_advanced",
            "success",
            metadata={"video_id": result.get("video_id"), "changed_fields": result.get("changed_fields", [])},
        )
        return result

    @server.tool(
        title="Restaurar metadados avançados anteriores do vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_video_metadata_rollback_advanced(
        rollback_payload: dict[str, Any],
        rollback_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        _require_scope(WRITE_SCOPE)
        _limit("write_rollback", limit=10)
        if user_confirmed is not True:
            _audit("mcp_video_metadata_rollback_advanced", "denied", metadata={"reason": "confirmation_missing"})
            raise ValueError("Confirmação explícita do usuário é obrigatória para executar rollback.")
        result = _service().apply_video_metadata_rollback(
            rollback_payload=rollback_payload,
            rollback_token=rollback_token,
        )
        _audit(
            "mcp_video_metadata_rollback_advanced",
            "success",
            metadata={"video_id": result.get("video_id"), "changed_fields": result.get("changed_fields", [])},
        )
        return result

    @server.tool(
        title="Listar legendas do vídeo",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def list_video_captions(video_id: str) -> dict[str, Any]:
        _require_scope(READ_SCOPE)
        _limit("caption_read", limit=60)
        return _service().list_video_captions(video_id=video_id)

    @server.tool(
        title="Preparar prévia de upload de legenda",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_caption_upload(
        video_id: str,
        language: str,
        content: str,
        name: str | None = None,
        caption_format: str = "srt",
    ) -> dict[str, Any]:
        _require_scope(WRITE_SCOPE)
        _limit("caption_preview", limit=20)
        result = _service().preview_caption_upload(
            video_id=video_id,
            language=language,
            content=content,
            name=name,
            caption_format=caption_format,
        )
        _audit(
            "mcp_caption_preview",
            "success",
            metadata={"video_id": video_id, "language": language, "caption_format": caption_format},
        )
        return result

    @server.tool(
        title="Enviar legenda aprovada para o vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_caption_upload(
        approval_payload: dict[str, Any],
        approval_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        _require_scope(WRITE_SCOPE)
        _limit("caption_apply", limit=10)
        if user_confirmed is not True:
            _audit("mcp_caption_apply", "denied", metadata={"reason": "confirmation_missing"})
            raise ValueError("Confirmação explícita do usuário é obrigatória para enviar a legenda.")
        result = _service().apply_caption_upload(
            approval_payload=approval_payload,
            approval_token=approval_token,
        )
        _audit(
            "mcp_caption_apply",
            "success",
            metadata={"video_id": result.get("video_id"), "caption_id": result.get("caption_id")},
        )
        return result

    @server.tool(
        title="Remover legenda criada pelo último upload",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_caption_delete_rollback(
        rollback_payload: dict[str, Any],
        rollback_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        _require_scope(WRITE_SCOPE)
        _limit("caption_rollback", limit=10)
        if user_confirmed is not True:
            _audit("mcp_caption_delete_rollback", "denied", metadata={"reason": "confirmation_missing"})
            raise ValueError("Confirmação explícita do usuário é obrigatória para remover a legenda.")
        result = _service().apply_caption_delete(
            rollback_payload=rollback_payload,
            rollback_token=rollback_token,
        )
        _audit(
            "mcp_caption_delete_rollback",
            "success",
            metadata={"video_id": result.get("video_id"), "caption_id": result.get("caption_id")},
        )
        return result

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
