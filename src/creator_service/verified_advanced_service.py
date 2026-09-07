from __future__ import annotations

import time
from typing import Any

from .advanced_service import AdvancedSafeCreatorService


class VerifiedAdvancedSafeCreatorService(AdvancedSafeCreatorService):
    """Advanced creator writes with a post-write read-back safety check.

    YouTube can occasionally accept a snippet update while not persisting every
    requested field. A successful API response is therefore not enough to claim
    success. This service reads the video back, verifies every mutable snippet
    field and automatically restores the exact previous metadata if any field
    was not persisted.
    """

    _VERIFY_FIELDS = ("title", "description", "tags", "categoryId", "defaultLanguage")

    def apply_video_metadata_update(self, *, approval_payload: dict, approval_token: str) -> dict:
        proposed = dict(approval_payload.get("proposed", {}) or {})
        video_id = str(proposed.get("video_id", "")).strip()
        if not video_id:
            raise ValueError("video_id ausente no payload aprovado.")

        before = self._current_video_snippet(video_id)
        result = super().apply_video_metadata_update(
            approval_payload=approval_payload,
            approval_token=approval_token,
        )
        expected = dict(result.get("rollback_preview", {}).get("current", {}) or {})

        persisted: dict[str, Any] | None = None
        mismatches: list[str] = []
        for attempt in range(5):
            persisted = self._current_video_snippet(video_id)
            mismatches = [
                key for key in self._VERIFY_FIELDS
                if persisted.get(key) != expected.get(key)
            ]
            if not mismatches:
                result["persisted_verified"] = True
                result["verification_attempts"] = attempt + 1
                return result
            if attempt < 4:
                time.sleep(1)

        restore_payload = dict(before)
        self._youtube().videos().update(
            part="snippet",
            body={"id": video_id, "snippet": self._snippet_for_update(restore_payload)},
        ).execute()
        restored = self._current_video_snippet(video_id)
        restore_mismatches = [
            key for key in self._VERIFY_FIELDS
            if restored.get(key) != before.get(key)
        ]
        self.memory.record_video_action(
            video_id=video_id,
            action_type="metadata_write_verification_rollback",
            surface="creator_service",
            changed_fields=list(mismatches),
            before=persisted or {},
            after=restored,
            details={
                "tenant_id": self.context.tenant_id,
                "reason": "youtube_write_not_fully_persisted",
                "mismatches": list(mismatches),
                "restore_mismatches": list(restore_mismatches),
            },
        )
        if restore_mismatches:
            raise RuntimeError(
                "O YouTube não persistiu todos os campos solicitados e a restauração automática "
                f"também divergiu nos campos: {', '.join(restore_mismatches)}."
            )
        raise RuntimeError(
            "O YouTube aceitou a atualização, mas não persistiu todos os campos solicitados "
            f"({', '.join(mismatches)}). A alteração parcial foi revertida automaticamente."
        )
