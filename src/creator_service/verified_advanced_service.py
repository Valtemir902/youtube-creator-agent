from __future__ import annotations

import time
from typing import Any

from .advanced_service import AdvancedSafeCreatorService
from .security import signer_from_env


class VerifiedAdvancedSafeCreatorService(AdvancedSafeCreatorService):
    """Advanced creator writes with defensive read-back and rollback checks.

    YouTube may acknowledge a snippet update before every read replica exposes
    the new value. This service therefore verifies writes over a bounded window,
    treats harmless whitespace normalization separately from real divergence,
    and re-bases rollback tokens on the metadata that was actually observed.
    """

    _VERIFY_FIELDS = ("title", "description", "tags", "categoryId", "defaultLanguage")
    _WRITE_VERIFY_DELAYS = (0.0, 1.0, 2.0, 4.0, 8.0)
    _RESTORE_VERIFY_DELAYS = (0.0, 1.0, 2.0, 4.0, 8.0, 15.0, 20.0)

    @staticmethod
    def _clean_write_tags(tags: list[str] | None) -> list[str] | None:
        """Normalize tags without the old SEO-only 12-tag truncation.

        YouTube constrains the aggregate tag payload, not this product to an
        arbitrary twelve items. Existing videos can legitimately contain more
        than twelve tags, so silently truncating them during an edit is unsafe.
        """
        if tags is None:
            return None
        clean: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            tag = " ".join(str(raw).strip().split())
            if not tag:
                continue
            key = tag.casefold()
            if key in seen:
                continue
            seen.add(key)
            clean.append(tag)
        # Be conservative about YouTube's 500-character aggregate tag budget:
        # tags containing spaces are effectively quoted in the serialized form.
        total = sum(len(tag) + (2 if " " in tag else 0) + 1 for tag in clean)
        if total > 500:
            raise ValueError("As tags ultrapassam o limite total seguro de 500 caracteres.")
        return clean

    @staticmethod
    def _normalize_metadata_payload(
        *,
        video_id: str,
        title: str | None,
        description: str | None,
        tags: list[str] | None,
        current: dict,
    ) -> dict:
        final_title = current["title"] if title is None else " ".join(title.strip().split())
        if not final_title:
            raise ValueError("Título não pode ficar vazio.")
        if len(final_title) > 100:
            raise ValueError("Título excede 100 caracteres.")
        final_description = current["description"] if description is None else description.strip()
        if len(final_description) > 5000:
            raise ValueError("Descrição excede 5.000 caracteres.")
        clean_tags = VerifiedAdvancedSafeCreatorService._clean_write_tags(tags)
        final_tags = current["tags"] if clean_tags is None else clean_tags
        return {
            "video_id": video_id.strip(),
            "title": final_title,
            "description": final_description,
            "tags": final_tags,
            "categoryId": current["categoryId"],
            "defaultLanguage": current.get("defaultLanguage"),
        }

    @staticmethod
    def _semantic_value(field: str, value: Any) -> Any:
        if field == "title":
            return " ".join(str(value or "").split())
        if field == "description":
            return str(value or "").replace("\r\n", "\n").replace("\r", "\n").rstrip()
        if field == "tags":
            return tuple(
                " ".join(str(item).strip().split())
                for item in (value or [])
                if " ".join(str(item).strip().split())
            )
        if field == "categoryId":
            return str(value or "")
        if field == "defaultLanguage":
            return str(value or "").strip().casefold()
        return value

    @classmethod
    def _mismatches(cls, actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
        return [
            field
            for field in cls._VERIFY_FIELDS
            if cls._semantic_value(field, actual.get(field)) != cls._semantic_value(field, expected.get(field))
        ]

    @classmethod
    def _exact_differences(cls, actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
        return [field for field in cls._VERIFY_FIELDS if actual.get(field) != expected.get(field)]

    def _wait_for_snippet(
        self,
        video_id: str,
        expected: dict[str, Any],
        delays: tuple[float, ...],
    ) -> tuple[dict[str, Any], list[str], list[str], int]:
        observed: dict[str, Any] = {}
        mismatches: list[str] = list(self._VERIFY_FIELDS)
        exact_differences: list[str] = list(self._VERIFY_FIELDS)
        for attempt, delay in enumerate(delays, start=1):
            if delay > 0:
                time.sleep(delay)
            observed = self._current_video_snippet(video_id)
            mismatches = self._mismatches(observed, expected)
            exact_differences = self._exact_differences(observed, expected)
            if not mismatches:
                return observed, mismatches, exact_differences, attempt
        return observed, mismatches, exact_differences, len(delays)

    def _build_rollback_package(
        self,
        *,
        video_id: str,
        persisted: dict[str, Any],
        restore: dict[str, Any],
    ) -> dict[str, Any]:
        # Sign exactly the normalized payload that apply_video_metadata_rollback
        # will reconstruct. This prevents harmless YouTube normalization from
        # making a freshly-issued rollback token unusable.
        normalized = self._normalize_metadata_payload(
            video_id=video_id,
            title=str(restore.get("title", "")),
            description=str(restore.get("description", "")),
            tags=list(restore.get("tags", []) or []),
            current=persisted,
        )
        normalized["categoryId"] = self._normalize_category_id(restore.get("categoryId"), persisted)
        normalized["defaultLanguage"] = restore.get("defaultLanguage") or persisted.get("defaultLanguage")
        signer = signer_from_env()
        payload = {
            "baseline_digest": signer.payload_digest(persisted),
            "proposed": normalized,
        }
        return {
            "current": persisted,
            "restore": normalized,
            "rollback_payload": payload,
            "rollback_token": signer.issue("rollback_video_metadata", video_id, payload),
            "expires_in_seconds": 900,
            "requires_explicit_user_confirmation": True,
        }

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

        persisted, mismatches, exact_differences, attempts = self._wait_for_snippet(
            video_id,
            expected,
            self._WRITE_VERIFY_DELAYS,
        )
        if not mismatches:
            result["persisted_verified"] = True
            result["verification_attempts"] = attempts
            result["normalization_differences"] = exact_differences
            result["rollback_preview"] = self._build_rollback_package(
                video_id=video_id,
                persisted=persisted,
                restore=before,
            )
            return result

        # A partial or stale write is not accepted as success. Restore the
        # pre-write snapshot and keep reading until the rollback propagates.
        self._youtube().videos().update(
            part="snippet",
            body={"id": video_id, "snippet": self._snippet_for_update(before)},
        ).execute()
        restored, restore_mismatches, restore_exact_differences, restore_attempts = self._wait_for_snippet(
            video_id,
            before,
            self._RESTORE_VERIFY_DELAYS,
        )
        self.memory.record_video_action(
            video_id=video_id,
            action_type="metadata_write_verification_rollback",
            surface="creator_service",
            changed_fields=list(mismatches),
            before=persisted,
            after=restored,
            details={
                "tenant_id": self.context.tenant_id,
                "reason": "youtube_write_not_fully_persisted",
                "mismatches": list(mismatches),
                "write_verification_attempts": attempts,
                "restore_mismatches": list(restore_mismatches),
                "restore_exact_differences": list(restore_exact_differences),
                "restore_verification_attempts": restore_attempts,
            },
        )
        if restore_mismatches:
            raise RuntimeError(
                "O YouTube não persistiu todos os campos solicitados e a restauração automática "
                f"não pôde ser confirmada nos campos: {', '.join(restore_mismatches)}."
            )
        raise RuntimeError(
            "O YouTube não confirmou todos os campos solicitados "
            f"({', '.join(mismatches)}). A alteração foi revertida automaticamente e a restauração foi verificada."
        )

    def apply_video_metadata_rollback(self, *, rollback_payload: dict, rollback_token: str) -> dict:
        proposed = dict(rollback_payload.get("proposed", {}) or {})
        video_id = str(proposed.get("video_id", "")).strip()
        if not video_id:
            raise ValueError("video_id ausente no payload de rollback.")

        current = self._current_video_snippet(video_id)
        expected = self._normalize_metadata_payload(
            video_id=video_id,
            title=str(proposed.get("title", "")),
            description=str(proposed.get("description", "")),
            tags=list(proposed.get("tags", []) or []),
            current=current,
        )
        expected["categoryId"] = self._normalize_category_id(proposed.get("categoryId"), current)
        expected["defaultLanguage"] = proposed.get("defaultLanguage") or current.get("defaultLanguage")

        result = super().apply_video_metadata_rollback(
            rollback_payload=rollback_payload,
            rollback_token=rollback_token,
        )
        restored, mismatches, exact_differences, attempts = self._wait_for_snippet(
            video_id,
            expected,
            self._RESTORE_VERIFY_DELAYS,
        )
        if mismatches:
            raise RuntimeError(
                "O rollback foi enviado ao YouTube, mas a leitura de confirmação ainda diverge nos campos: "
                f"{', '.join(mismatches)}."
            )
        result["persisted_verified"] = True
        result["verification_attempts"] = attempts
        result["normalization_differences"] = exact_differences
        result["verified_current"] = restored
        return result
