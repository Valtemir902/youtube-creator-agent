from __future__ import annotations

import io
import re
from typing import Any

from googleapiclient.http import MediaIoBaseUpload

from .safe_service import SafeCreatorService
from .security import signer_from_env


_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_ALLOWED_CAPTION_FORMATS = {"srt", "vtt"}
_CAPTION_MIME = {
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
}


class AdvancedSafeCreatorService(SafeCreatorService):
    """Safe write extensions used by the ChatGPT MCP surface.

    Adds category changes and caption upload while preserving the existing
    signed-preview, explicit-confirmation and rollback model.
    """

    @staticmethod
    def _normalize_category_id(category_id: str | None, current: dict[str, Any]) -> str:
        if category_id is None:
            return str(current.get("categoryId", "22"))
        value = str(category_id).strip()
        if not value.isdigit() or not (1 <= len(value) <= 3):
            raise ValueError("category_id deve ser um ID numérico válido do YouTube.")
        return value

    def list_video_categories(self, region_code: str = "BR") -> dict[str, Any]:
        self.context.validate_youtube()
        region = (region_code or "BR").strip().upper()
        if len(region) != 2 or not region.isalpha():
            raise ValueError("region_code deve ter duas letras, por exemplo BR.")
        response = self._youtube().videoCategories().list(part="snippet", regionCode=region).execute()
        return {
            "region_code": region,
            "categories": [
                {
                    "id": str(item.get("id", "")),
                    "title": str(item.get("snippet", {}).get("title", "")),
                    "assignable": bool(item.get("snippet", {}).get("assignable", False)),
                }
                for item in response.get("items", [])
            ],
        }

    def preview_video_metadata_update(
        self,
        *,
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        category_id: str | None = None,
    ) -> dict[str, Any]:
        self.context.validate_youtube()
        self.memory.assert_not_recently_edited(video_id)
        current = self._current_video_snippet(video_id)
        proposed = self._normalize_metadata_payload(
            video_id=video_id,
            title=title,
            description=description,
            tags=tags,
            current=current,
        )
        proposed["categoryId"] = self._normalize_category_id(category_id, current)
        proposed["defaultLanguage"] = current.get("defaultLanguage")
        envelope = self._approval_envelope(current, proposed)
        approval_token = signer_from_env().issue(
            "update_video_metadata",
            proposed["video_id"],
            envelope,
        )
        changed = {
            key: current.get(key) != proposed.get(key)
            for key in ("title", "description", "tags", "categoryId")
        }
        return {
            "video_id": proposed["video_id"],
            "current": current,
            "proposed": proposed,
            "changed": changed,
            "approval_payload": envelope,
            "approval_token": approval_token,
            "expires_in_seconds": 900,
            "requires_explicit_user_confirmation": True,
            "recent_edit_protection": self.video_memory_state(proposed["video_id"]),
        }

    def apply_video_metadata_update(self, *, approval_payload: dict, approval_token: str) -> dict:
        self.context.validate_youtube()
        proposed = dict(approval_payload.get("proposed", {}) or {})
        video_id = str(proposed.get("video_id", "")).strip()
        if not video_id:
            raise ValueError("video_id ausente no payload aprovado.")

        self.memory.assert_not_recently_edited(video_id)
        current = self._current_video_snippet(video_id)
        signer = signer_from_env()
        baseline_digest = str(approval_payload.get("baseline_digest", ""))
        if not baseline_digest or baseline_digest != signer.payload_digest(current):
            raise RuntimeError("O vídeo mudou desde a prévia. Gere uma nova prévia antes de aplicar.")

        normalized = self._normalize_metadata_payload(
            video_id=video_id,
            title=str(proposed.get("title", "")),
            description=str(proposed.get("description", "")),
            tags=list(proposed.get("tags", []) or []),
            current=current,
        )
        normalized["categoryId"] = self._normalize_category_id(proposed.get("categoryId"), current)
        normalized["defaultLanguage"] = current.get("defaultLanguage")
        normalized_envelope = {"baseline_digest": baseline_digest, "proposed": normalized}
        signer.verify(
            approval_token,
            action="update_video_metadata",
            subject=video_id,
            payload=normalized_envelope,
        )

        response = self._youtube().videos().update(
            part="snippet",
            body={"id": video_id, "snippet": self._snippet_for_update(normalized)},
        ).execute()
        changed_fields = [
            key for key in ("title", "description", "tags", "categoryId")
            if current.get(key) != normalized.get(key)
        ]
        self.memory.record_video_action(
            video_id=video_id,
            action_type="metadata_update",
            surface="creator_service",
            changed_fields=changed_fields,
            before=current,
            after=normalized,
            details={"tenant_id": self.context.tenant_id},
        )

        rollback_proposed = {
            "video_id": video_id,
            "title": current["title"],
            "description": current["description"],
            "tags": list(current.get("tags", []) or []),
            "categoryId": current["categoryId"],
            "defaultLanguage": current.get("defaultLanguage"),
        }
        rollback_payload = {
            "baseline_digest": signer.payload_digest(self._digestable_snippet(normalized)),
            "proposed": rollback_proposed,
        }
        rollback_token = signer.issue("rollback_video_metadata", video_id, rollback_payload)
        return {
            "ok": True,
            "video_id": video_id,
            "title": response.get("snippet", {}).get("title", normalized["title"]),
            "changed_fields": changed_fields,
            "recent_edit_protection": self.video_memory_state(video_id),
            "rollback_preview": {
                "current": normalized,
                "restore": rollback_proposed,
                "rollback_payload": rollback_payload,
                "rollback_token": rollback_token,
                "expires_in_seconds": 900,
                "requires_explicit_user_confirmation": True,
            },
        }

    def apply_video_metadata_rollback(self, *, rollback_payload: dict, rollback_token: str) -> dict:
        self.context.validate_youtube()
        proposed = dict(rollback_payload.get("proposed", {}) or {})
        video_id = str(proposed.get("video_id", "")).strip()
        if not video_id:
            raise ValueError("video_id ausente no payload de rollback.")

        current = self._current_video_snippet(video_id)
        signer = signer_from_env()
        baseline_digest = str(rollback_payload.get("baseline_digest", ""))
        if not baseline_digest or baseline_digest != signer.payload_digest(current):
            raise RuntimeError(
                "O vídeo mudou desde a edição. O rollback automático foi bloqueado para não sobrescrever uma alteração mais recente."
            )

        normalized = self._normalize_metadata_payload(
            video_id=video_id,
            title=str(proposed.get("title", "")),
            description=str(proposed.get("description", "")),
            tags=list(proposed.get("tags", []) or []),
            current=current,
        )
        normalized["categoryId"] = self._normalize_category_id(proposed.get("categoryId"), current)
        normalized["defaultLanguage"] = proposed.get("defaultLanguage") or current.get("defaultLanguage")
        normalized_envelope = {"baseline_digest": baseline_digest, "proposed": normalized}
        signer.verify(
            rollback_token,
            action="rollback_video_metadata",
            subject=video_id,
            payload=normalized_envelope,
        )
        response = self._youtube().videos().update(
            part="snippet",
            body={"id": video_id, "snippet": self._snippet_for_update(normalized)},
        ).execute()
        changed_fields = [
            key for key in ("title", "description", "tags", "categoryId")
            if current.get(key) != normalized.get(key)
        ]
        self.memory.record_video_action(
            video_id=video_id,
            action_type="metadata_rollback",
            surface="creator_service",
            changed_fields=changed_fields,
            before=current,
            after=normalized,
            details={"tenant_id": self.context.tenant_id},
        )
        return {
            "ok": True,
            "rolled_back": True,
            "video_id": video_id,
            "title": response.get("snippet", {}).get("title", normalized["title"]),
            "changed_fields": changed_fields,
            "recent_edit_protection": self.video_memory_state(video_id),
        }

    def list_video_captions(self, video_id: str) -> dict[str, Any]:
        self.context.validate_youtube()
        video_id = str(video_id).strip()
        if not video_id:
            raise ValueError("video_id é obrigatório.")
        response = self._youtube().captions().list(part="snippet", videoId=video_id).execute()
        return {
            "video_id": video_id,
            "captions": [
                {
                    "id": str(item.get("id", "")),
                    "language": str(item.get("snippet", {}).get("language", "")),
                    "name": str(item.get("snippet", {}).get("name", "")),
                    "track_kind": str(item.get("snippet", {}).get("trackKind", "")),
                    "status": str(item.get("snippet", {}).get("status", "")),
                    "is_draft": bool(item.get("snippet", {}).get("isDraft", False)),
                }
                for item in response.get("items", [])
            ],
        }

    @staticmethod
    def _normalize_caption_payload(
        *, video_id: str,
        language: str,
        content: str,
        name: str | None,
        caption_format: str,
    ) -> dict[str, Any]:
        video_id = str(video_id).strip()
        language = str(language).strip()
        fmt = str(caption_format or "srt").strip().lower()
        text = str(content).replace("\r\n", "\n").strip()
        display_name = " ".join(str(name or "").strip().split())
        if not video_id:
            raise ValueError("video_id é obrigatório.")
        if not _LANGUAGE_RE.fullmatch(language):
            raise ValueError("language deve ser um código BCP-47 simples, por exemplo pt-BR.")
        if fmt not in _ALLOWED_CAPTION_FORMATS:
            raise ValueError("caption_format deve ser srt ou vtt.")
        if not text:
            raise ValueError("O conteúdo da legenda não pode ficar vazio.")
        if len(text.encode("utf-8")) > 1_000_000:
            raise ValueError("A legenda excede o limite seguro de 1 MB por operação.")
        if fmt == "vtt" and not text.lstrip().startswith("WEBVTT"):
            raise ValueError("Legenda VTT deve começar com WEBVTT.")
        if fmt == "srt" and "-->" not in text:
            raise ValueError("Legenda SRT inválida: nenhum intervalo de tempo foi encontrado.")
        if len(display_name) > 150:
            raise ValueError("O nome da faixa de legenda excede 150 caracteres.")
        return {
            "video_id": video_id,
            "language": language,
            "name": display_name,
            "caption_format": fmt,
            "content": text,
        }

    def preview_caption_upload(
        self,
        *,
        video_id: str,
        language: str,
        content: str,
        name: str | None = None,
        caption_format: str = "srt",
    ) -> dict[str, Any]:
        self.context.validate_youtube()
        proposed = self._normalize_caption_payload(
            video_id=video_id,
            language=language,
            content=content,
            name=name,
            caption_format=caption_format,
        )
        token = signer_from_env().issue("upload_video_caption", proposed["video_id"], proposed)
        return {
            "video_id": proposed["video_id"],
            "language": proposed["language"],
            "name": proposed["name"],
            "caption_format": proposed["caption_format"],
            "content_bytes": len(proposed["content"].encode("utf-8")),
            "approval_payload": proposed,
            "approval_token": token,
            "expires_in_seconds": 900,
            "requires_explicit_user_confirmation": True,
        }

    def apply_caption_upload(self, *, approval_payload: dict, approval_token: str) -> dict[str, Any]:
        self.context.validate_youtube()
        proposed = self._normalize_caption_payload(
            video_id=str(approval_payload.get("video_id", "")),
            language=str(approval_payload.get("language", "")),
            content=str(approval_payload.get("content", "")),
            name=approval_payload.get("name"),
            caption_format=str(approval_payload.get("caption_format", "srt")),
        )
        signer = signer_from_env()
        signer.verify(
            approval_token,
            action="upload_video_caption",
            subject=proposed["video_id"],
            payload=proposed,
        )
        media = MediaIoBaseUpload(
            io.BytesIO(proposed["content"].encode("utf-8")),
            mimetype=_CAPTION_MIME[proposed["caption_format"]],
            resumable=False,
        )
        body = {
            "snippet": {
                "videoId": proposed["video_id"],
                "language": proposed["language"],
                "name": proposed["name"],
                "isDraft": False,
            }
        }
        response = self._youtube().captions().insert(
            part="snippet",
            body=body,
            media_body=media,
        ).execute()
        caption_id = str(response.get("id", ""))
        if not caption_id:
            raise RuntimeError("O YouTube não retornou o ID da legenda criada.")
        rollback_payload = {"caption_id": caption_id, "video_id": proposed["video_id"]}
        rollback_token = signer.issue("delete_uploaded_caption", caption_id, rollback_payload)
        self.memory.record_video_action(
            video_id=proposed["video_id"],
            action_type="caption_upload",
            surface="creator_service",
            changed_fields=["captions"],
            before={},
            after={"caption_id": caption_id, "language": proposed["language"], "name": proposed["name"]},
            details={"tenant_id": self.context.tenant_id},
        )
        return {
            "ok": True,
            "video_id": proposed["video_id"],
            "caption_id": caption_id,
            "language": proposed["language"],
            "name": proposed["name"],
            "rollback_preview": {
                "rollback_payload": rollback_payload,
                "rollback_token": rollback_token,
                "expires_in_seconds": 900,
                "requires_explicit_user_confirmation": True,
            },
        }

    def apply_caption_delete(self, *, rollback_payload: dict, rollback_token: str) -> dict[str, Any]:
        self.context.validate_youtube()
        caption_id = str(rollback_payload.get("caption_id", "")).strip()
        video_id = str(rollback_payload.get("video_id", "")).strip()
        if not caption_id or not video_id:
            raise ValueError("caption_id e video_id são obrigatórios no rollback.")
        signer_from_env().verify(
            rollback_token,
            action="delete_uploaded_caption",
            subject=caption_id,
            payload={"caption_id": caption_id, "video_id": video_id},
        )
        self._youtube().captions().delete(id=caption_id).execute()
        self.memory.record_video_action(
            video_id=video_id,
            action_type="caption_delete_rollback",
            surface="creator_service",
            changed_fields=["captions"],
            before={"caption_id": caption_id},
            after={},
            details={"tenant_id": self.context.tenant_id},
        )
        return {"ok": True, "deleted": True, "caption_id": caption_id, "video_id": video_id}
