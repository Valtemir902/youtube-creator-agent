from __future__ import annotations

from typing import Any

from .mcp_errors import tool_error
from .security import signer_from_env
from .verified_advanced_service import VerifiedAdvancedSafeCreatorService


class ResponsibleCreatorService(VerifiedAdvancedSafeCreatorService):
    """Single high-assurance executor for AI-originated YouTube mutations.

    The model is never trusted with target identity. This service re-reads the
    authenticated channel and exact video immediately before mutation, verifies
    the signed baseline, verifies persistence after mutation and compensates a
    provider-owned partial write before the MCP request can time out.
    """

    # Keep the complete synchronous mutation lifecycle comfortably bounded for
    # ChatGPT/MCP callers. Long verification sleeps previously allowed a partial
    # provider write to outlive the tool request before compensation executed.
    _WRITE_VERIFY_DELAYS = (0.0, 0.25, 0.75, 1.5)
    _RESTORE_VERIFY_DELAYS = (0.0, 0.25, 0.75, 1.5, 2.5)
    _AMBIGUOUS_VERIFY_DELAYS = (0.0, 0.25, 0.75, 1.5)

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

    def _is_provider_partial_state(
        self,
        *,
        before: dict[str, Any],
        expected: dict[str, Any],
        observed: dict[str, Any],
    ) -> bool:
        """Return True only for a state composed exclusively of before/expected values."""
        saw_before = False
        saw_expected = False
        for field in self._VERIFY_FIELDS:
            old = self._semantic_value(field, before.get(field))
            new = self._semantic_value(field, expected.get(field))
            got = self._semantic_value(field, observed.get(field))
            if got == old:
                saw_before = True
                continue
            if got == new:
                saw_expected = True
                continue
            return False
        return saw_before and saw_expected

    def _restore_verified_snapshot(
        self,
        *,
        video_id: str,
        before: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str], list[str], int]:
        restore_error: Exception | None = None
        try:
            self._youtube().videos().update(
                part="snippet",
                body={"id": video_id, "snippet": self._snippet_for_update(before)},
            ).execute()
        except Exception as exc:
            restore_error = exc

        try:
            restored, mismatches, exact_differences, attempts = self._wait_for_snippet(
                video_id,
                before,
                self._RESTORE_VERIFY_DELAYS,
            )
        except Exception as exc:
            raise tool_error(
                "write_state_uncertain",
                "A gravação não pôde ser confirmada e a releitura da restauração também falhou. O estado remoto precisa ser relido antes de outra escrita.",
            ) from exc

        if mismatches:
            raise tool_error(
                "write_state_uncertain",
                "Foi detectada uma gravação parcial e a restauração automática não pôde ser confirmada integralmente. O estado remoto precisa ser relido antes de outra escrita.",
            ) from restore_error
        return restored, mismatches, exact_differences, attempts

    def _partial_write_error(self) -> Exception:
        return tool_error(
            "partial_write_detected",
            "O YouTube persistiu apenas parte dos metadados aprovados. A ferramenta restaurou e verificou o snapshot anterior; gere uma nova prévia antes de tentar novamente.",
        )

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
        try:
            observed, mismatches, exact_differences, attempts = self._wait_for_snippet(
                video_id,
                expected,
                self._AMBIGUOUS_VERIFY_DELAYS,
            )
        except Exception as exc:
            raise tool_error(
                "write_state_uncertain",
                "A resposta da gravação falhou e o estado remoto não pôde ser relido com segurança.",
            ) from exc

        if not mismatches:
            return self._success_result(
                video_id=video_id,
                before=before,
                persisted=observed,
                attempts=attempts,
                exact_differences=exact_differences,
                recovered_from_ambiguous_response=True,
            )

        if not self._mismatches(observed, before):
            raise original_error

        if self._is_provider_partial_state(before=before, expected=expected, observed=observed):
            self._restore_verified_snapshot(video_id=video_id, before=before)
            raise self._partial_write_error() from original_error

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
        raise tool_error(
            "write_state_uncertain",
            "A resposta do YouTube falhou e foi detectado um valor que não pertence nem ao snapshot anterior nem à proposta aprovada. Novas alterações ficam bloqueadas para não sobrescrever uma possível edição externa.",
        ) from original_error

    def apply_video_metadata_update(self, *, approval_payload: dict, approval_token: str) -> dict[str, Any]:
        self.context.validate_youtube()
        proposed = dict(approval_payload.get("proposed", {}) or {})
        video_id = str(proposed.get("video_id", "")).strip()
        if not video_id:
            raise tool_error("invalid_request", "video_id ausente no payload aprovado.")

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

        try:
            persisted, mismatches, exact_differences, attempts = self._wait_for_snippet(
                video_id,
                expected,
                self._WRITE_VERIFY_DELAYS,
            )
        except Exception as exc:
            try:
                observed = self._current_video_snippet(video_id)
            except Exception as read_exc:
                raise tool_error(
                    "write_state_uncertain",
                    "O YouTube aceitou a chamada de gravação, mas a verificação posterior falhou e o estado remoto não pôde ser relido.",
                ) from read_exc
            if not self._mismatches(observed, before) and self._mismatches(observed, expected):
                raise tool_error(
                    "youtube_api_error",
                    "A chamada de gravação foi aceita, mas nenhuma alteração ficou visível antes de a verificação falhar.",
                ) from exc
            if self._is_provider_partial_state(before=before, expected=expected, observed=observed):
                self._restore_verified_snapshot(video_id=video_id, before=before)
                raise self._partial_write_error() from exc
            if not self._mismatches(observed, expected):
                return self._success_result(
                    video_id=video_id,
                    before=before,
                    persisted=observed,
                    attempts=1,
                    exact_differences=[],
                    recovered_from_ambiguous_response=True,
                )
            raise tool_error(
                "write_state_uncertain",
                "A verificação pós-gravação falhou e o estado remoto contém valores fora do snapshot/proposta assinados.",
            ) from exc

        if not mismatches:
            return self._success_result(
                video_id=video_id,
                before=before,
                persisted=persisted,
                attempts=attempts,
                exact_differences=exact_differences,
            )

        if self._is_provider_partial_state(before=before, expected=expected, observed=persisted):
            self._restore_verified_snapshot(video_id=video_id, before=before)
            raise self._partial_write_error()

        if not self._mismatches(persisted, before):
            raise tool_error(
                "youtube_api_error",
                "O YouTube respondeu à atualização, mas o readback permaneceu integralmente no snapshot anterior. Nenhuma alteração foi aceita.",
            )

        self.memory.record_video_action(
            video_id=video_id,
            action_type="metadata_write_ambiguous_state",
            surface="responsible_creator_service",
            changed_fields=self._changed_fields(before, persisted),
            before=before,
            after=persisted,
            details={
                "tenant_id": self.context.tenant_id,
                "reason": "confirmed_response_with_third_party_value",
                "mismatches": list(mismatches),
                "verification_attempts": attempts,
            },
        )
        raise tool_error(
            "write_state_uncertain",
            "O readback contém valor diferente tanto do snapshot anterior quanto da proposta aprovada. A ferramenta não fará restauração automática para não sobrescrever possível edição externa.",
        )
