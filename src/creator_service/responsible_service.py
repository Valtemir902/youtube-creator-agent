from __future__ import annotations

from typing import Any

from .mcp_errors import tool_error
from .security import signer_from_env
from .verified_advanced_service import VerifiedAdvancedSafeCreatorService


class ResponsibleCreatorService(VerifiedAdvancedSafeCreatorService):
    """Single high-assurance executor for AI-originated YouTube mutations.

    The model is never trusted with target identity. This service re-reads the
    authenticated channel and exact video immediately before mutation, verifies
    the signed baseline, verifies persistence after mutation and refuses to
    overwrite a divergent state when the outcome of a network request is
    ambiguous.
    """

    _AMBIGUOUS_VERIFY_DELAYS = (0.0, 1.0, 2.0, 4.0, 8.0)

    def _expected_from_approval(self, approval_payload: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        proposed = dict(approval_payload.get("proposed", {}) or {})
        video_id = str(proposed.get("video_id", "")).strip()
        normalized = self._normalize_metadata_payload(
            video_id=video_id,
            title=str(proposed.get("title", "")),
            description=str(proposed.get("description", "")),
            tags=list(proposed.get("tags", []) or []),
            current=current,
        )
        normalized["categoryId"] = self._normalize_category_id(proposed.get("categoryId"), current)
        normalized["defaultLanguage"] = proposed.get("defaultLanguage") or current.get("defaultLanguage")
        return normalized

    def _changed_fields(self, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        return [
            field
            for field in self._VERIFY_FIELDS
            if self._semantic_value(field, before.get(field)) != self._semantic_value(field, after.get(field))
        ]

    def _success_result(
        self,
        *,
        video_id: str,
        before: dict[str, Any],
        persisted: dict[str, Any],
        attempts: int,
        exact_differences: list[str],
        recovered_from_ambiguous_response: bool = False,
    ) -> dict[str, Any]:
        changed_fields = self._changed_fields(before, persisted)
        self.memory.record_video_action(
            video_id=video_id,
            action_type=("metadata_update_recovered" if recovered_from_ambiguous_response else "metadata_update"),
            surface="responsible_creator_service",
            changed_fields=changed_fields,
            before=before,
            after=persisted,
            details={
                "tenant_id": self.context.tenant_id,
                "persisted_verified": True,
                "recovered_from_ambiguous_response": recovered_from_ambiguous_response,
            },
        )
        return {
            "ok": True,
            "video_id": video_id,
            "title": persisted.get("title", ""),
            "changed_fields": changed_fields,
            "persisted_verified": True,
            "verification_attempts": attempts,
            "normalization_differences": exact_differences,
            "recovered_from_ambiguous_response": recovered_from_ambiguous_response,
            "verified_current": persisted,
            "recent_edit_protection": self.video_memory_state(video_id),
            "rollback_preview": self._build_rollback_package(
                video_id=video_id,
                persisted=persisted,
                restore=before,
            ),
        }

    def _resolve_ambiguous_write(
        self,
        *,
        video_id: str,
        before: dict[str, Any],
        expected: dict[str, Any],
        original_error: Exception,
    ) -> dict[str, Any]:
        observed, mismatches, exact_differences, attempts = self._wait_for_snippet(
            video_id,
            expected,
            self._AMBIGUOUS_VERIFY_DELAYS,
        )
        if not mismatches:
            # The transport failed, but the authoritative YouTube read-back says
            # the exact approved state persisted. Do not retry the mutation.
            return self._success_result(
                video_id=video_id,
                before=before,
                persisted=observed,
                attempts=attempts,
                exact_differences=exact_differences,
                recovered_from_ambiguous_response=True,
            )

        if not self._mismatches(observed, before):
            # No approved change is visible after the bounded read-back window.
            # Preserve the original provider error instead of pretending success.
            raise original_error

        # The state is neither the original baseline nor the exact approved
        # payload. It may contain a partial provider write or a concurrent human
        # edit. Restoring automatically could overwrite someone else's work, so
        # the only responsible behavior is to stop and surface an explicit
        # uncertain-state error for inspection.
        self.memory.record_video_action(
            video_id=video_id,
            action_type="metadata_write_ambiguous_state",
            surface="responsible_creator_service",
            changed_fields=self._changed_fields(before, observed),
            before=before,
            after=observed,
            details={
                "tenant_id": self.context.tenant_id,
                "reason": "transport_failed_and_state_diverged",
                "provider_error_type": type(original_error).__name__,
                "expected_mismatches": mismatches,
                "verification_attempts": attempts,
            },
        )
        raise RuntimeError(
            "A resposta do YouTube falhou e o estado atual ficou diferente tanto da versão anterior quanto da versão aprovada. "
            "A ferramenta bloqueou novas alterações para não sobrescrever uma possível edição externa."
        ) from original_error

    def apply_video_metadata_update(self, *, approval_payload: dict, approval_token: str) -> dict[str, Any]:
        self.context.validate_youtube()
        proposed = dict(approval_payload.get("proposed", {}) or {})
        video_id = str(proposed.get("video_id", "")).strip()
        if not video_id:
            raise ValueError("video_id ausente no payload aprovado.")

        self.memory.assert_not_recently_edited(video_id)
        before = self._current_video_snippet(video_id)
        signer = signer_from_env()
        baseline_digest = str(approval_payload.get("baseline_digest", "")).strip()
        if not baseline_digest or baseline_digest != signer.payload_digest(before):
            raise tool_error(
                "external_change_detected",
                "O vídeo mudou desde a prévia. Gere uma nova prévia antes de aplicar.",
            )

        expected = self._expected_from_approval(approval_payload, before)
        normalized_envelope = {"baseline_digest": baseline_digest, "proposed": expected}
        signer.verify(
            approval_token,
            action="update_video_metadata",
            subject=video_id,
            payload=normalized_envelope,
        )

        snippet = self._snippet_for_update(expected)
        try:
            self._youtube().videos().update(
                part="snippet",
                body={"id": video_id, "snippet": snippet},
            ).execute()
        except Exception as exc:
            return self._resolve_ambiguous_write(
                video_id=video_id,
                before=before,
                expected=expected,
                original_error=exc,
            )

        persisted, mismatches, exact_differences, attempts = self._wait_for_snippet(
            video_id,
            expected,
            self._WRITE_VERIFY_DELAYS,
        )
        if not mismatches:
            return self._success_result(
                video_id=video_id,
                before=before,
                persisted=persisted,
                attempts=attempts,
                exact_differences=exact_differences,
            )

        # A confirmed response with a partial/stale persisted state is safe to
        # restore because we know this request reached the provider and the
        # before snapshot is the baseline we signed immediately before writing.
        try:
            self._youtube().videos().update(
                part="snippet",
                body={"id": video_id, "snippet": self._snippet_for_update(before)},
            ).execute()
        except Exception as restore_error:
            restored, restore_mismatches, _, restore_attempts = self._wait_for_snippet(
                video_id,
                before,
                self._RESTORE_VERIFY_DELAYS,
            )
            if not restore_mismatches:
                raise RuntimeError(
                    "O YouTube não persistiu todos os campos solicitados. A resposta da restauração falhou, "
                    "mas a leitura final confirmou que o estado anterior foi restaurado."
                ) from restore_error
            self.memory.record_video_action(
                video_id=video_id,
                action_type="metadata_restore_ambiguous_state",
                surface="responsible_creator_service",
                changed_fields=self._changed_fields(before, restored),
                before=persisted,
                after=restored,
                details={
                    "tenant_id": self.context.tenant_id,
                    "restore_mismatches": restore_mismatches,
                    "restore_verification_attempts": restore_attempts,
                },
            )
            raise RuntimeError(
                "O YouTube persistiu um estado parcial e a restauração automática não pôde ser confirmada. "
                "Novas alterações devem permanecer bloqueadas até uma releitura segura."
            ) from restore_error

        restored, restore_mismatches, restore_exact_differences, restore_attempts = self._wait_for_snippet(
            video_id,
            before,
            self._RESTORE_VERIFY_DELAYS,
        )
        self.memory.record_video_action(
            video_id=video_id,
            action_type="metadata_write_verification_rollback",
            surface="responsible_creator_service",
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
                "O YouTube não persistiu todos os campos solicitados e a restauração automática não pôde ser confirmada nos campos: "
                f"{', '.join(restore_mismatches)}."
            )
        raise RuntimeError(
            "O YouTube não confirmou todos os campos solicitados "
            f"({', '.join(mismatches)}). A alteração foi revertida automaticamente e a restauração foi verificada."
        )
