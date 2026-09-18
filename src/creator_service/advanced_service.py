from __future__ import annotations

import io
import re
import time
from typing import Any

from googleapiclient.http import MediaIoBaseUpload

from .caption_quality import process_srt
from .mcp_errors import tool_error
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

    # Video-control writes are intentionally isolated from metadata/caption paths; this marker promotes the validated runtime.
    _VIDEO_STATUS_WRITABLE_FIELDS = (
        "privacyStatus",
        "publishAt",
        "license",
        "embeddable",
        "publicStatsViewable",
        "selfDeclaredMadeForKids",
    )
    _VIDEO_CONTROL_VERIFY_DELAYS = (0.0, 0.25, 0.75, 1.5)

    @classmethod
    def _writable_video_status(cls, status: dict[str, Any]) -> dict[str, Any]:
        return {
            field: status[field]
            for field in cls._VIDEO_STATUS_WRITABLE_FIELDS
            if field in status and status[field] is not None
        }

    @staticmethod
    def _video_identity_snapshot(item: dict[str, Any]) -> dict[str, Any]:
        snippet = item.get("snippet", {}) or {}
        status = item.get("status", {}) or {}
        return {
            "video_id": str(item.get("id", "")),
            "channel_id": str(snippet.get("channelId", "")),
            "title": str(snippet.get("title", "")),
            "privacy_status": str(status.get("privacyStatus", "")),
            "published_at": snippet.get("publishedAt"),
        }

    @classmethod
    def _video_control_baseline(cls, item: dict[str, Any]) -> dict[str, Any]:
        snippet = item.get("snippet", {}) or {}
        return {
            "video_id": str(item.get("id", "")),
            "channel_id": str(snippet.get("channelId", "")),
            "snippet": {
                "title": str(snippet.get("title", "")),
                "description": str(snippet.get("description", "")),
                "tags": list(snippet.get("tags", []) or []),
                "categoryId": str(snippet.get("categoryId", "22")),
                "defaultLanguage": snippet.get("defaultLanguage"),
            },
            "status": cls._writable_video_status(item.get("status", {}) or {}),
        }

    def _owned_video_control_item(self, video_id: str) -> dict[str, Any]:
        return self._owned_video_item(video_id, part="snippet,status")

    def _video_absent(self, video_id: str) -> bool:
        response = self._youtube().videos().list(part="snippet", id=video_id).execute()
        items = response.get("items", [])
        if not items:
            return True
        item = dict(items[0])
        owner = str((item.get("snippet", {}) or {}).get("channelId", "")).strip()
        if owner != self._authorized_channel_id():
            raise tool_error("video_not_owned")
        return False

    def preview_video_privacy_update(self, *, video_id: str, privacy_status: str) -> dict[str, Any]:
        self.context.validate_youtube()
        target = str(privacy_status or "").strip().lower()
        if target not in {"public", "unlisted", "private"}:
            raise ValueError("privacy_status deve ser public, unlisted ou private.")
        item = self._owned_video_control_item(video_id)
        current = self._video_identity_snapshot(item)
        proposed = dict(current)
        proposed["privacy_status"] = target
        baseline = self._video_control_baseline(item)
        approval_payload = {
            "baseline_digest": signer_from_env().payload_digest(baseline),
            "proposed": {
                "video_id": current["video_id"],
                "privacy_status": target,
            },
        }
        token = signer_from_env().issue(
            "update_video_privacy",
            current["video_id"],
            approval_payload,
        )
        return {
            "video_id": current["video_id"],
            "current": current,
            "proposed": proposed,
            "changed": current["privacy_status"] != target,
            "approval_payload": approval_payload,
            "approval_token": token,
            "expires_in_seconds": 900,
            "requires_explicit_user_confirmation": True,
        }

    def apply_video_privacy_update(
        self,
        *,
        approval_payload: dict[str, Any],
        approval_token: str,
    ) -> dict[str, Any]:
        self.context.validate_youtube()
        proposed = dict(approval_payload.get("proposed", {}) or {})
        video_id = str(proposed.get("video_id", "")).strip()
        target = str(proposed.get("privacy_status", "")).strip().lower()
        if not video_id:
            raise ValueError("video_id ausente no payload aprovado.")
        if target not in {"public", "unlisted", "private"}:
            raise ValueError("privacy_status deve ser public, unlisted ou private.")

        signer = signer_from_env()
        normalized_payload = {
            "baseline_digest": str(approval_payload.get("baseline_digest", "")),
            "proposed": {"video_id": video_id, "privacy_status": target},
        }
        signer.verify(
            approval_token,
            action="update_video_privacy",
            subject=video_id,
            payload=normalized_payload,
        )

        item = self._owned_video_control_item(video_id)
        before_identity = self._video_identity_snapshot(item)
        before_baseline = self._video_control_baseline(item)
        if signer.payload_digest(before_baseline) != normalized_payload["baseline_digest"]:
            raise tool_error("external_change_detected")

        if before_identity["privacy_status"] == target:
            observed = before_identity
            rollback_preview = None
            return {
                "ok": True,
                "video_id": video_id,
                "persisted_verified": True,
                "no_changes": True,
                "current": observed,
                "changed_fields": [],
                "verification_attempts": 0,
                "rollback_preview": rollback_preview,
            }

        status_body = dict(before_baseline["status"])
        status_body["privacyStatus"] = target
        if target != "private":
            status_body.pop("publishAt", None)

        request = self._youtube().videos().update(
            part="status",
            body={"id": video_id, "status": status_body},
        )
        etag = str(item.get("etag", "") or "").strip()
        if etag:
            headers = getattr(request, "headers", None)
            if headers is None:
                raise tool_error(
                    "write_state_uncertain",
                    "A atualização condicional de privacidade não está disponível neste cliente. Nenhuma gravação foi enviada.",
                )
            headers["If-Match"] = etag
        request.execute()

        observed_item: dict[str, Any] | None = None
        verification_attempts = 0
        for delay in self._VIDEO_CONTROL_VERIFY_DELAYS:
            if delay:
                time.sleep(delay)
            verification_attempts += 1
            candidate = self._owned_video_control_item(video_id)
            if self._video_identity_snapshot(candidate)["privacy_status"] == target:
                observed_item = candidate
                break

        if observed_item is None:
            raise tool_error(
                "write_state_uncertain",
                "O YouTube recebeu a atualização de privacidade, mas o estado final aprovado não pôde ser confirmado por leitura. Nenhum retry foi executado.",
            )

        observed_identity = self._video_identity_snapshot(observed_item)
        observed_baseline = self._video_control_baseline(observed_item)
        if observed_baseline["snippet"] != before_baseline["snippet"]:
            raise tool_error(
                "write_state_uncertain",
                "A privacidade foi alterada, mas o readback detectou mudança concorrente no snippet do vídeo.",
            )
        for field, value in before_baseline["status"].items():
            if field in {"privacyStatus", "publishAt"}:
                continue
            if observed_baseline["status"].get(field) != value:
                raise tool_error(
                    "write_state_uncertain",
                    "A privacidade foi alterada, mas o readback detectou mudança concorrente em outro campo de status.",
                )

        rollback_payload = {
            "baseline_digest": signer.payload_digest(observed_baseline),
            "proposed": {
                "video_id": video_id,
                "privacy_status": before_identity["privacy_status"],
            },
        }
        rollback_token = signer.issue("update_video_privacy", video_id, rollback_payload)
        return {
            "ok": True,
            "video_id": video_id,
            "persisted_verified": True,
            "current": observed_identity,
            "changed_fields": ["privacyStatus"],
            "verification_attempts": verification_attempts,
            "rollback_preview": {
                "rollback_payload": rollback_payload,
                "rollback_token": rollback_token,
                "restore_privacy_status": before_identity["privacy_status"],
                "apply_tool": "apply_video_privacy_update",
                "expires_in_seconds": 900,
                "requires_explicit_user_confirmation": True,
            },
        }

    def preview_video_delete(self, *, video_id: str) -> dict[str, Any]:
        self.context.validate_youtube()
        item = self._owned_video_control_item(video_id)
        snapshot = self._video_identity_snapshot(item)
        baseline = self._video_control_baseline(item)
        approval_payload = {
            "video_id": snapshot["video_id"],
            "baseline_digest": signer_from_env().payload_digest(baseline),
            "snapshot": snapshot,
            "irreversible": True,
        }
        token = signer_from_env().issue(
            "delete_video",
            snapshot["video_id"],
            approval_payload,
        )
        return {
            "video_id": snapshot["video_id"],
            "snapshot": snapshot,
            "approval_payload": approval_payload,
            "approval_token": token,
            "expires_in_seconds": 900,
            "requires_explicit_user_confirmation": True,
            "irreversible": True,
            "rollback_supported": False,
            "warning": "A exclusão de vídeo no YouTube é definitiva e não possui rollback pela API.",
        }

    def apply_video_delete(
        self,
        *,
        approval_payload: dict[str, Any],
        approval_token: str,
    ) -> dict[str, Any]:
        self.context.validate_youtube()
        video_id = str(approval_payload.get("video_id", "")).strip()
        if not video_id:
            raise ValueError("video_id ausente no payload aprovado.")
        signer = signer_from_env()
        signer.verify(
            approval_token,
            action="delete_video",
            subject=video_id,
            payload=approval_payload,
        )

        item = self._owned_video_control_item(video_id)
        current_baseline = self._video_control_baseline(item)
        baseline_digest = str(approval_payload.get("baseline_digest", ""))
        if not baseline_digest or signer.payload_digest(current_baseline) != baseline_digest:
            raise tool_error("external_change_detected")

        request = self._youtube().videos().delete(id=video_id)
        recovered_from_ambiguous_response = False
        try:
            request.execute()
        except Exception as exc:
            try:
                absent = self._video_absent(video_id)
            except Exception as read_exc:
                raise tool_error(
                    "write_state_uncertain",
                    "A resposta da exclusão foi ambígua e o estado remoto não pôde ser confirmado. Nenhum retry foi executado.",
                ) from read_exc
            if not absent:
                raise tool_error(
                    "youtube_api_error",
                    "A exclusão falhou e o readback confirmou que o vídeo ainda existe. Nenhum retry foi executado.",
                ) from exc
            recovered_from_ambiguous_response = True

        verification_attempts = 0
        deleted_verified = False
        for delay in self._VIDEO_CONTROL_VERIFY_DELAYS:
            if delay:
                time.sleep(delay)
            verification_attempts += 1
            if self._video_absent(video_id):
                deleted_verified = True
                break
        if not deleted_verified:
            raise tool_error(
                "write_state_uncertain",
                "A chamada de exclusão retornou, mas a ausência remota do vídeo não pôde ser confirmada. Nenhum retry foi executado.",
            )

        return {
            "ok": True,
            "video_id": video_id,
            "deleted_verified": True,
            "verification_attempts": verification_attempts,
            "recovered_from_ambiguous_response": recovered_from_ambiguous_response,
            "rollback_supported": False,
            "irreversible": True,
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
    def _video_duration_seconds(value: str | None) -> float | None:
        # YouTube contentDetails.duration is ISO 8601 (for example PT10S or PT1H2M3.5S).
        match = re.fullmatch(
            r"P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+(?:\.\d+)?)S)?)?",
            str(value or ""),
        )
        if not match:
            return None
        return (
            float(match.group("d") or 0) * 86400
            + float(match.group("h") or 0) * 3600
            + float(match.group("m") or 0) * 60
            + float(match.group("s") or 0)
        )

    @staticmethod
    def _caption_language_matches(track_language: str | None, requested: str) -> bool:
        track = str(track_language or "").casefold()
        wanted = str(requested or "").casefold()
        return bool(track and wanted and (track == wanted or track.split("-", 1)[0] == wanted.split("-", 1)[0]))

    def _caption_context(self, video_id: str, language: str) -> dict[str, Any]:
        tracks = list(
            self._youtube().captions().list(part="snippet", videoId=video_id).execute().get("items", [])
        )
        manual_same_language: list[dict[str, Any]] = []
        source_track: dict[str, Any] | None = None
        for track in tracks:
            snippet = track.get("snippet", {}) or {}
            if not self._caption_language_matches(snippet.get("language"), language):
                continue
            is_auto = str(snippet.get("trackKind", "")).upper() == "ASR"
            published = not bool(snippet.get("isDraft", False))
            if not is_auto and published:
                manual_same_language.append(track)
            if source_track is None and is_auto:
                source_track = track
        if source_track is None:
            for track in tracks:
                snippet = track.get("snippet", {}) or {}
                if str(snippet.get("trackKind", "")).upper() == "ASR":
                    source_track = track
                    break
        source_snippet = (source_track or {}).get("snippet", {}) or {}
        return {
            "tracks": tracks,
            "manual_same_language": manual_same_language,
            "manual_caption_already_exists": bool(manual_same_language),
            "source_track_kind": str(source_snippet.get("trackKind", "")) or None,
            "source_caption_id": str((source_track or {}).get("id", "")) or None,
        }

    @staticmethod
    def _normalize_caption_payload(
        *,
        video_id: str,
        language: str,
        content: str,
        name: str | None,
        caption_format: str,
        caption_mode: str = "auto",
        preserve_sdh_markers: bool = False,
        existing_manual_action: str | None = None,
    ) -> dict[str, Any]:
        video_id = str(video_id).strip()
        language = str(language).strip()
        fmt = str(caption_format or "srt").strip().lower()
        text = str(content).replace("\r\n", "\n").replace("\r", "\n").strip()
        display_name = " ".join(str(name or "").strip().split())
        mode = str(caption_mode or "auto").strip().lower()
        manual_action = str(existing_manual_action or "").strip().lower() or None
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
        if mode not in {"auto", "speech", "music"}:
            raise ValueError("caption_mode deve ser auto, speech ou music.")
        if manual_action not in {None, "keep", "separate", "replace"}:
            raise ValueError("existing_manual_action deve ser keep, separate ou replace.")
        return {
            "video_id": video_id,
            "language": language,
            "name": display_name,
            "caption_format": fmt,
            "content": text,
            "caption_mode": mode,
            "preserve_sdh_markers": bool(preserve_sdh_markers),
            "existing_manual_action": manual_action,
        }

    def preview_caption_upload(
        self,
        *,
        video_id: str,
        language: str,
        content: str,
        name: str | None = None,
        caption_format: str = "srt",
        caption_mode: str = "auto",
        preserve_sdh_markers: bool = False,
        existing_manual_action: str | None = None,
    ) -> dict[str, Any]:
        self.context.validate_youtube()
        proposed = self._normalize_caption_payload(
            video_id=video_id,
            language=language,
            content=content,
            name=name,
            caption_format=caption_format,
            caption_mode=caption_mode,
            preserve_sdh_markers=preserve_sdh_markers,
            existing_manual_action=existing_manual_action,
        )
        video = self._owned_video_item(proposed["video_id"], part="snippet,contentDetails")
        duration = self._video_duration_seconds((video.get("contentDetails", {}) or {}).get("duration"))
        context = self._caption_context(proposed["video_id"], proposed["language"])

        validation: dict[str, Any] = {
            "validation_passed": True,
            "validation_errors": [],
            "validation_warnings": [],
            "cue_count": None,
            "overlap_count": None,
            "empty_cue_count": None,
            "malformed_cue_count": None,
            "duration_coverage": None,
            "estimated_readability": None,
        }
        if proposed["caption_format"] == "srt":
            music_mode = proposed["caption_mode"] == "music"
            quality = process_srt(
                proposed["content"],
                video_duration=duration,
                preserve_sdh_markers=proposed["preserve_sdh_markers"],
                music_mode=music_mode,
            )
            processed_content = quality.pop("content").strip()
            if quality["validation_passed"]:
                proposed["content"] = processed_content
            validation.update(quality)

        manual_exists = context["manual_caption_already_exists"]
        manual_action = proposed["existing_manual_action"]
        apply_allowed = bool(validation["validation_passed"])
        if manual_exists:
            if manual_action is None:
                validation["validation_errors"].append("manual_caption_decision_required")
                apply_allowed = False
            elif manual_action == "keep":
                validation["validation_warnings"].append("manual_caption_keep_selected_no_upload_needed")
                apply_allowed = False
            elif manual_action == "replace":
                validation["validation_errors"].append("manual_caption_replace_not_supported_by_safe_upload_flow")
                apply_allowed = False
            elif manual_action == "separate" and not proposed["name"]:
                validation["validation_errors"].append("separate_manual_caption_requires_name")
                apply_allowed = False

        validation["validation_errors"] = list(dict.fromkeys(validation["validation_errors"]))
        validation["validation_warnings"] = list(dict.fromkeys(validation["validation_warnings"]))
        validation["validation_passed"] = not validation["validation_errors"]
        apply_allowed = apply_allowed and validation["validation_passed"]

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
            **validation,
            "source_track_kind": context["source_track_kind"],
            "source_caption_id": context["source_caption_id"],
            "manual_caption_already_exists": manual_exists,
            "manual_caption_decision": manual_action,
            "manual_caption_decision_options": {
                "keep": True,
                "separate": True,
                "replace": False,
            },
            "apply_allowed": apply_allowed,
        }

    def apply_caption_upload(self, *, approval_payload: dict, approval_token: str) -> dict[str, Any]:
        self.context.validate_youtube()
        proposed = self._normalize_caption_payload(
            video_id=str(approval_payload.get("video_id", "")),
            language=str(approval_payload.get("language", "")),
            content=str(approval_payload.get("content", "")),
            name=approval_payload.get("name"),
            caption_format=str(approval_payload.get("caption_format", "srt")),
            caption_mode=str(approval_payload.get("caption_mode", "auto")),
            preserve_sdh_markers=bool(approval_payload.get("preserve_sdh_markers", False)),
            existing_manual_action=approval_payload.get("existing_manual_action"),
        )
        signer = signer_from_env()
        signer.verify(
            approval_token,
            action="upload_video_caption",
            subject=proposed["video_id"],
            payload=proposed,
        )

        video = self._owned_video_item(proposed["video_id"], part="snippet,contentDetails")
        duration = self._video_duration_seconds((video.get("contentDetails", {}) or {}).get("duration"))
        if proposed["caption_format"] == "srt":
            quality = process_srt(
                proposed["content"],
                video_duration=duration,
                preserve_sdh_markers=proposed["preserve_sdh_markers"],
                music_mode=proposed["caption_mode"] == "music",
            )
            if not quality["validation_passed"]:
                raise ValueError(
                    "A publicação foi bloqueada porque o SRT falhou na validação estrutural: "
                    + ", ".join(quality["validation_errors"])
                )
            if quality["content"].strip() != proposed["content"]:
                raise ValueError("O conteúdo aprovado não corresponde mais à normalização determinística do SRT.")

        context = self._caption_context(proposed["video_id"], proposed["language"])
        if context["manual_caption_already_exists"]:
            action = proposed["existing_manual_action"]
            if action != "separate":
                raise ValueError(
                    "Já existe legenda manual publicada no mesmo idioma. "
                    "Gere nova prévia e escolha explicitamente keep ou separate."
                )
            if not proposed["name"]:
                raise ValueError("Uma faixa manual separada exige nome explícito.")
        if proposed["existing_manual_action"] == "replace":
            raise ValueError("Replace não é suportado pelo fluxo seguro atual; nenhuma faixa foi alterada.")

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

        verified_track: dict[str, Any] | None = None
        verification_attempts = 0
        for delay in (0.0, 0.5, 1.0, 2.0):
            if delay:
                time.sleep(delay)
            verification_attempts += 1
            tracks = self._youtube().captions().list(
                part="snippet", videoId=proposed["video_id"]
            ).execute().get("items", [])
            verified_track = next(
                (item for item in tracks if str(item.get("id", "")) == caption_id),
                None,
            )
            if verified_track:
                snippet = verified_track.get("snippet", {}) or {}
                if (
                    str(snippet.get("trackKind", "")).lower() == "standard"
                    and str(snippet.get("status", "")).lower() == "serving"
                    and bool(snippet.get("isDraft", False)) is False
                ):
                    break
            verified_track = None

        if verified_track is None:
            raise RuntimeError(
                "A legenda foi enviada, mas a publicação não pôde ser confirmada como standard/serving/is_draft:false. "
                "Não repita a escrita antes de diagnosticar o estado remoto."
            )

        final_tracks = self._youtube().captions().list(
            part="snippet", videoId=proposed["video_id"]
        ).execute().get("items", [])
        has_published_manual_caption = any(
            str((item.get("snippet", {}) or {}).get("trackKind", "")).upper() != "ASR"
            and not bool((item.get("snippet", {}) or {}).get("isDraft", False))
            for item in final_tracks
        )
        if not has_published_manual_caption:
            raise RuntimeError(
                "O readback não confirmou has_published_manual_caption:true; a operação não será marcada como sucesso."
            )

        snippet = verified_track.get("snippet", {}) or {}
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
            "persisted_verified": True,
            "video_id": proposed["video_id"],
            "caption_id": caption_id,
            "language": proposed["language"],
            "name": proposed["name"],
            "track_kind": str(snippet.get("trackKind", "")),
            "status": str(snippet.get("status", "")),
            "is_draft": bool(snippet.get("isDraft", False)),
            "has_published_manual_caption": True,
            "verification_attempts": verification_attempts,
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
