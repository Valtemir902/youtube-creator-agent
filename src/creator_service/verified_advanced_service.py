from __future__ import annotations

import time
from typing import Any

from .advanced_service import AdvancedSafeCreatorService
from .mcp_errors import tool_error
from .security import signer_from_env


class VerifiedAdvancedSafeCreatorService(AdvancedSafeCreatorService):
    """Advanced creator writes with defensive read-back and compensation.

    The verified path owns the complete mutation lifecycle. A remote write is not
    recorded as successful until every approved field has been observed on a
    bounded read-back and a rollback package has been prepared. Any exception
    after the mutation request is sent is treated as an ambiguous write: the
    service reads the remote state and restores the pre-write snapshot when
    necessary before surfacing a structured error.
    """

    _VERIFY_FIELDS = ("title", "description", "tags", "categoryId", "defaultLanguage")
    _WRITE_VERIFY_DELAYS = (0.0, 1.0, 2.0, 4.0, 8.0)
    _RESTORE_VERIFY_DELAYS = (0.0, 1.0, 2.0, 4.0, 8.0, 15.0, 20.0)

    @staticmethod
    def _clean_write_tags(tags: list[str] | None) -> list[str] | None:
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

    def _prepare_verified_update(
        self,
        *,
        approval_payload: dict,
        approval_token: str,
    ) -> tuple[str, dict[str, Any], dict[str, Any], list[str]]:
        self.context.validate_youtube()
        proposed = dict(approval_payload.get("proposed", {}) or {})
        video_id = str(proposed.get("video_id", "")).strip()
        if not video_id:
            raise ValueError("video_id ausente no payload aprovado.")

        self.memory.assert_not_recently_edited(video_id)
        before = self._current_video_snippet(video_id)
        signer = signer_from_env()
        baseline_digest = str(approval_payload.get("baseline_digest", ""))
        if not baseline_digest or baseline_digest != signer.payload_digest(before):
            raise RuntimeError("O vídeo mudou desde a prévia. Gere uma nova prévia antes de aplicar.")

        expected = self._normalize_metadata_payload(
            video_id=video_id,
            title=str(proposed.get("title", "")),
            description=str(proposed.get("description", "")),
            tags=list(proposed.get("tags", []) or []),
            current=before,
        )
        expected["categoryId"] = self._normalize_category_id(proposed.get("categoryId"), before)
        expected["defaultLanguage"] = before.get("defaultLanguage")
        normalized_envelope = {"baseline_digest": baseline_digest, "proposed": expected}
        signer.verify(
            approval_token,
            action="update_video_metadata",
            subject=video_id,
            payload=normalized_envelope,
        )
        changed_fields = [
            key
            for key in ("title", "description", "tags", "categoryId")
            if before.get(key) != expected.get(key)
        ]
        return video_id, before, expected, changed_fields

    def _restore_snapshot_after_ambiguous_write(
        self,
        *,
        video_id: str,
        before: dict[str, Any],
        observed: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], list[str], list[str], int]:
        current = observed if observed is not None else self._current_video_snippet(video_id)
        if not self._mismatches(current, before):
            return current, [], self._exact_differences(current, before), 1

        self._youtube().videos().update(
            part="snippet",
            body={"id": video_id, "snippet": self._snippet_for_update(before)},
        ).execute()
        return self._wait_for_snippet(video_id, before, self._RESTORE_VERIFY_DELAYS)

    def _compensate_or_raise_uncertain(
        self,
        *,
        video_id: str,
        before: dict[str, Any],
        observed: dict[str, Any] | None,
        original: BaseException | None = None,
    ) -> None:
        try:
            _, restore_mismatches, _, _ = self._restore_snapshot_after_ambiguous_write(
                video_id=video_id,
                before=before,
                observed=observed,
            )
        except Exception as restore_exc:
            raise tool_error(
                "write_state_uncertain",
                "A gravação falhou após uma possível alteração remota e a restauração automática não pôde ser confirmada.",
            ) from restore_exc
        if restore_mismatches:
            raise tool_error(
                "write_state_uncertain",
                "A gravação ficou divergente e a restauração automática não pôde ser confirmada nos campos: "
                + ", ".join(restore_mismatches),
            ) from original
        raise tool_error(
            "partial_write_detected",
            "A gravação não foi confirmada integralmente. O estado anterior foi restaurado e verificado.",
        ) from original

    def apply_video_metadata_update(self, *, approval_payload: dict, approval_token: str) -> dict:
        video_id, before, expected, changed_fields = self._prepare_verified_update(
            approval_payload=approval_payload,
            approval_token=approval_token,
        )

        response: dict[str, Any] = {}
        try:
            response = self._youtube().videos().update(
                part="snippet",
                body={"id": video_id, "snippet": self._snippet_for_update(expected)},
            ).execute()
        except Exception as exc:
            # A client/transport exception can happen after YouTube accepted the
            # request. Probe the remote state and compensate if it changed.
            try:
                observed = self._current_video_snippet(video_id)
            except Exception:
                raise tool_error(
                    "write_state_uncertain",
                    "A chamada de atualização falhou e o estado remoto não pôde ser confirmado.",
                ) from exc
            if self._mismatches(observed, before):
                self._compensate_or_raise_uncertain(
                    video_id=video_id,
                    before=before,
                    observed=observed,
                    original=exc,
                )
            raise

        persisted, mismatches, exact_differences, attempts = self._wait_for_snippet(
            video_id,
            expected,
            self._WRITE_VERIFY_DELAYS,
        )
        if mismatches:
            self._compensate_or_raise_uncertain(
                video_id=video_id,
                before=before,
                observed=persisted,
            )

        # Prepare rollback before creating the recent-edit memory record. If any
        # local finalization step fails, restore the remote snapshot and do not
        # mark the failed attempt as a successful recent edit.
        try:
            rollback_preview = self._build_rollback_package(
                video_id=video_id,
                persisted=persisted,
                restore=before,
            )
            self.memory.record_video_action(
                video_id=video_id,
                action_type="metadata_update",
                surface="creator_service",
                changed_fields=changed_fields,
                before=before,
                after=persisted,
                details={"tenant_id": self.context.tenant_id, "verification_attempts": attempts},
            )
        except Exception as exc:
            self._compensate_or_raise_uncertain(
                video_id=video_id,
                before=before,
                observed=persisted,
                original=exc,
            )

        # Protection-state rendering is informational. A failure to read it after
        # a verified, recorded write must not turn a completed write into an
        # ambiguous internal error.
        try:
            protection = self.video_memory_state(video_id)
        except Exception:
            protection = {"protected": True, "state_available": False}

        return {
            "ok": True,
            "video_id": video_id,
            "title": response.get("snippet", {}).get("title", persisted["title"]),
            "changed_fields": changed_fields,
            "recent_edit_protection": protection,
            "persisted_verified": True,
            "verification_attempts": attempts,
            "normalization_differences": exact_differences,
            "rollback_preview": rollback_preview,
        }

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
            raise tool_error(
                "write_state_uncertain",
                "O rollback foi enviado ao YouTube, mas a leitura de confirmação ainda diverge nos campos: "
                + ", ".join(mismatches),
            )
        result["persisted_verified"] = True
        result["verification_attempts"] = attempts
        result["normalization_differences"] = exact_differences
        result["verified_current"] = restored
        return result
