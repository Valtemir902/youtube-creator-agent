from __future__ import annotations

from typing import Any

from .security import signer_from_env
from .service import CreatorService


class SafeCreatorService(CreatorService):
    """CreatorService with an explicit, signed, short-lived rollback path."""

    @staticmethod
    def _snippet_for_update(normalized: dict[str, Any]) -> dict[str, Any]:
        snippet = {
            "title": normalized["title"],
            "description": normalized["description"],
            "tags": normalized["tags"],
            "categoryId": normalized["categoryId"],
        }
        if normalized.get("defaultLanguage"):
            snippet["defaultLanguage"] = normalized["defaultLanguage"]
        return snippet

    @staticmethod
    def _digestable_snippet(metadata: dict[str, Any]) -> dict[str, Any]:
        """Canonical remote snippet shape used for baseline comparisons."""
        return {
            "title": str(metadata.get("title", "")),
            "description": str(metadata.get("description", "")),
            "tags": list(metadata.get("tags", []) or []),
            "categoryId": str(metadata.get("categoryId", "22")),
            "defaultLanguage": metadata.get("defaultLanguage"),
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
        normalized["categoryId"] = current["categoryId"]
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
            key for key in ("title", "description", "tags")
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
        rollback_token = signer.issue(
            "rollback_video_metadata",
            video_id,
            rollback_payload,
        )

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
        """Restore exactly the pre-update metadata using the one signed rollback package.

        This intentionally bypasses the generic recent-edit guard, but only for the exact
        short-lived rollback payload issued by a successful write. Any intervening change,
        modified payload, wrong target or expired token is rejected before YouTube is written.
        """
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
        normalized["categoryId"] = current["categoryId"]
        normalized["defaultLanguage"] = current.get("defaultLanguage")
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
            key for key in ("title", "description", "tags")
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
