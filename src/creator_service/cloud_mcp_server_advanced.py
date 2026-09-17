from __future__ import annotations

import os
from typing import Any

from mcp.types import ToolAnnotations

from . import cloud_mcp_server as base
from .verified_advanced_service import VerifiedAdvancedSafeCreatorService


def _service() -> VerifiedAdvancedSafeCreatorService:
    resolver = base._resolver()
    context = resolver.resolve(base._tenant_id())
    return VerifiedAdvancedSafeCreatorService(context)


def create_server():
    # Existing tools keep their names/contracts, but resolve through the verified
    # advanced service as well. This prevents legacy metadata writes from
    # reporting success before YouTube has actually persisted every field.
    base._service = _service
    server = base.create_server()

    @server.tool(
        title="Listar categorias de vídeo do YouTube",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False, idempotent_hint=True),
    )
    def list_video_categories(region_code: str = "BR") -> dict[str, Any]:
        base._require_scope(base.READ_SCOPE)
        base._limit("categories", limit=60)
        return _service().list_video_categories(region_code)

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
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("write_preview", limit=30)
            result = _service().preview_video_metadata_update(
                video_id=video_id,
                title=title,
                description=description,
                tags=tags,
                category_id=category_id,
            )
            base._audit(
                "mcp_video_metadata_advanced_preview",
                "success",
                {"video_id": video_id, "changed": result.get("changed", {})},
            )
            return base.success_response(result)

        return base._structured("preview_video_metadata_update_advanced", action)

    @server.tool(
        title="Aplicar metadados avançados aprovados no vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_video_metadata_update_advanced(
        approval_payload: dict[str, Any],
        approval_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("write_apply", limit=15)
            if user_confirmed is not True:
                base._audit("mcp_video_metadata_advanced_apply", "denied", {"reason": "confirmation_missing"})
                raise base.tool_error("confirmation_required")
            video_id = base._consume_signed_write(
                token=approval_token,
                payload=approval_payload,
                action="update_video_metadata",
            )
            try:
                result = _service().apply_video_metadata_update(
                    approval_payload=approval_payload,
                    approval_token=approval_token,
                )
            except Exception:
                base._audit("mcp_video_metadata_advanced_apply", "failed", {"video_id": video_id})
                raise
            base._audit(
                "mcp_video_metadata_advanced_apply",
                "success",
                {"video_id": result.get("video_id"), "changed_fields": result.get("changed_fields", [])},
            )
            return base.success_response(result)

        return base._structured("apply_video_metadata_update_advanced", action)

    @server.tool(
        title="Restaurar metadados avançados anteriores do vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_video_metadata_rollback_advanced(
        rollback_payload: dict[str, Any],
        rollback_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("write_rollback", limit=10)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            video_id = base._consume_signed_write(
                token=rollback_token,
                payload=rollback_payload,
                action="rollback_video_metadata",
            )
            try:
                result = _service().apply_video_metadata_rollback(
                    rollback_payload=rollback_payload,
                    rollback_token=rollback_token,
                )
            except Exception:
                base._audit("mcp_video_metadata_advanced_rollback", "failed", {"video_id": video_id})
                raise
            base._audit(
                "mcp_video_metadata_advanced_rollback",
                "success",
                {"video_id": result.get("video_id"), "changed_fields": result.get("changed_fields", [])},
            )
            return base.success_response(result)

        return base._structured("apply_video_metadata_rollback_advanced", action)

    @server.tool(
        title="Listar legendas do vídeo",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False, idempotent_hint=True),
    )
    def list_video_captions(video_id: str) -> dict[str, Any]:
        base._require_scope(base.READ_SCOPE)
        base._limit("captions_read", limit=60)
        return _service().list_video_captions(video_id)

    @server.tool(
        title="Preparar prévia de envio de legenda",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_caption_upload(
        video_id: str,
        language: str,
        content: str,
        name: str | None = None,
        caption_format: str = "srt",
    ) -> dict[str, Any]:
        base._require_scope(base.WRITE_SCOPE)
        base._limit("caption_preview", limit=20)
        result = _service().preview_caption_upload(
            video_id=video_id,
            language=language,
            content=content,
            name=name,
            caption_format=caption_format,
        )
        base._audit("mcp_caption_preview", "success", {"video_id": video_id, "language": language})
        return result

    @server.tool(
        title="Enviar legenda aprovada ao vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_caption_upload(
        approval_payload: dict[str, Any],
        approval_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        base._require_scope(base.WRITE_SCOPE)
        base._limit("caption_apply", limit=10)
        if user_confirmed is not True:
            raise ValueError("Confirmação explícita do usuário é obrigatória para enviar a legenda.")
        result = _service().apply_caption_upload(
            approval_payload=approval_payload,
            approval_token=approval_token,
        )
        base._audit(
            "mcp_caption_upload",
            "success",
            {"video_id": result.get("video_id"), "caption_id": result.get("caption_id")},
        )
        return result

    @server.tool(
        title="Excluir a legenda criada usando rollback aprovado",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_caption_delete_rollback(
        rollback_payload: dict[str, Any],
        rollback_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        base._require_scope(base.WRITE_SCOPE)
        base._limit("caption_rollback", limit=10)
        if user_confirmed is not True:
            raise ValueError("Confirmação explícita do usuário é obrigatória para excluir a legenda.")
        result = _service().apply_caption_delete(
            rollback_payload=rollback_payload,
            rollback_token=rollback_token,
        )
        base._audit(
            "mcp_caption_delete_rollback",
            "success",
            {"video_id": result.get("video_id"), "caption_id": result.get("caption_id")},
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
