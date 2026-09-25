from __future__ import annotations

import json
import logging
import time
from typing import Any

from .mcp_errors import CreatorToolError, tool_error
from .security import signer_from_env
from .verified_advanced_service import VerifiedAdvancedSafeCreatorService


logger = logging.getLogger(__name__)


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
    # Final read-only settlement window for YouTube eventual consistency.
    # Production evidence showed tag rollback becoming visible only after the
    # bounded compensation phase; no mutation is sent during this phase.
    _ROLLBACK_SETTLE_VERIFY_DELAYS = (0.0, 2.0, 4.0, 6.0)
    _MAX_RESTORE_WRITES = 2

    @staticmethod
    def _snippet_from_item(item: dict[str, Any]) -> dict[str, Any]:
        snippet = dict(item.get("snippet", {}) or {})
        return {
            "title": str(snippet.get("title", "")),
            "description": str(snippet.get("description", "")),
            "tags": list(snippet.get("tags", []) or []),
            "categoryId": str(snippet.get("categoryId", "22")),
            "defaultLanguage": snippet.get("defaultLanguage"),
        }

    def _versioned_video_snippet(self, video_id: str) -> tuple[dict[str, Any], str]:
        item = self._owned_video_item(video_id, part="snippet")
        return self._snippet_from_item(item), str(item.get("etag", "") or "").strip()

    def _conditional_snippet_update(
        self,
        *,
        video_id: str,
        snippet: dict[str, Any],
        etag: str,
    ) -> dict[str, Any]:
        request = self._youtube().videos().update(
            part="snippet",
            body={"id": video_id, "snippet": snippet},
        )
        # googleapiclient.http.HttpRequest exposes a mutable headers mapping.
        # Use If-Match whenever YouTube supplied an ETag so a concurrent edit
        # fails instead of being overwritten by this request.
        if etag:
            headers = getattr(request, "headers", None)
            if headers is None:
                raise tool_error(
                    "write_state_uncertain",
                    "A atualização segura por versão não está disponível neste cliente. Nenhuma gravação foi enviada.",
                )
            headers["If-Match"] = etag
        return request.execute()

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

    def _verification_report(
        self,
        *,
        expected: dict[str, Any],
        observed: dict[str, Any],
    ) -> dict[str, Any]:
        mismatched_fields = self._mismatches(observed, expected)
        field_matches = {
            "title_matches": "title" not in mismatched_fields,
            "description_matches": "description" not in mismatched_fields,
            "tags_match": "tags" not in mismatched_fields,
            "category_matches": "categoryId" not in mismatched_fields,
            "default_language_matches": "defaultLanguage" not in mismatched_fields,
        }
        return {
            "restored_and_verified": not mismatched_fields,
            "expected_snapshot": {field: expected.get(field) for field in self._VERIFY_FIELDS},
            "observed_snapshot": {field: observed.get(field) for field in self._VERIFY_FIELDS},
            "mismatched_fields": list(mismatched_fields),
            **field_matches,
            "field_matches": field_matches,
        }

    def _provider_field_states(
        self,
        *,
        before: dict[str, Any],
        expected: dict[str, Any],
        observed: dict[str, Any],
    ) -> dict[str, str]:
        """Classify fields without logging or exposing any metadata values."""
        states: dict[str, str] = {}
        for field in self._VERIFY_FIELDS:
            old = self._semantic_value(field, before.get(field))
            new = self._semantic_value(field, expected.get(field))
            got = self._semantic_value(field, observed.get(field))
            if got == new:
                states[field] = "expected"
            elif got == old:
                states[field] = "before"
            else:
                states[field] = "other"
        return states

    def _log_partial_state(
        self,
        *,
        video_id: str,
        before: dict[str, Any],
        expected: dict[str, Any],
        observed: dict[str, Any],
        phase: str,
        verification_attempts: int | None = None,
    ) -> None:
        logger.warning(
            json.dumps(
                {
                    "event": "metadata_partial_write_state",
                    "video_id": video_id,
                    "phase": phase,
                    "field_states": self._provider_field_states(
                        before=before,
                        expected=expected,
                        observed=observed,
                    ),
                    "verification_attempts": verification_attempts,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )

    def _is_provider_partial_state(
        self,
        *,
        before: dict[str, Any],
        expected: dict[str, Any],
        observed: dict[str, Any],
    ) -> bool:
        """Return True only for a state composed exclusively of before/expected values."""
        states = self._provider_field_states(before=before, expected=expected, observed=observed)
        values = set(states.values())
        return "other" not in values and "before" in values and "expected" in values

    def _record_uncertain_restore(
        self,
        *,
        video_id: str,
        before: dict[str, Any],
        observed: dict[str, Any],
        reason: str,
        restore_writes: int,
        verification_attempts: int | None = None,
    ) -> None:
        self.memory.record_video_action(
            video_id=video_id,
            action_type="metadata_restore_uncertain_state",
            surface="responsible_creator_service",
            changed_fields=self._changed_fields(before, observed),
            before=before,
            after=observed,
            details={
                "tenant_id": self.context.tenant_id,
                "reason": reason,
                "restore_writes": restore_writes,
                "verification_attempts": verification_attempts,
            },
        )

    def _restore_verified_snapshot(
        self,
        *,
        video_id: str,
        before: dict[str, Any],
        expected: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str], list[str], int]:
        """Restore the signed pre-write snapshot without retrying the user update.

        A provider may itself partially apply a compensation update. We allow one
        bounded reconciliation write only while every remotely observed field is
        still one of the two authenticated values (before/expected). Any third
        value stops compensation immediately and activates recent-edit protection.
        """
        last_observed = dict(before)
        last_mismatches: list[str] = []
        last_exact: list[str] = []
        total_verification_attempts = 0

        for restore_write in range(1, self._MAX_RESTORE_WRITES + 1):
            try:
                current, etag = self._versioned_video_snippet(video_id)
            except Exception as exc:
                self._record_uncertain_restore(
                    video_id=video_id,
                    before=before,
                    observed=last_observed,
                    reason="restore_prewrite_read_failed",
                    restore_writes=restore_write - 1,
                    verification_attempts=total_verification_attempts,
                )
                raise tool_error(
                    "write_state_uncertain",
                    "A restauração foi interrompida porque o estado remoto não pôde ser relido com segurança.",
                ) from exc

            last_observed = current
            if not self._mismatches(current, before):
                return current, [], self._exact_differences(current, before), max(1, total_verification_attempts)

            states = self._provider_field_states(before=before, expected=expected, observed=current)
            if "other" in states.values():
                self._log_partial_state(
                    video_id=video_id,
                    before=before,
                    expected=expected,
                    observed=current,
                    phase=f"restore_prewrite_{restore_write}",
                    verification_attempts=total_verification_attempts or None,
                )
                self._record_uncertain_restore(
                    video_id=video_id,
                    before=before,
                    observed=current,
                    reason="restore_prewrite_third_value",
                    restore_writes=restore_write - 1,
                    verification_attempts=total_verification_attempts,
                )
                raise tool_error(
                    "write_state_uncertain",
                    "A restauração foi interrompida porque apareceu um valor que não pertence ao snapshot anterior nem à proposta aprovada. O vídeo foi protegido contra novas escritas automáticas.",
                )

            restore_error: Exception | None = None
            try:
                self._conditional_snippet_update(
                    video_id=video_id,
                    snippet=self._snippet_for_update(before),
                    etag=etag,
                )
            except Exception as exc:
                restore_error = exc

            try:
                restored, mismatches, exact_differences, attempts = self._wait_for_snippet(
                    video_id,
                    before,
                    self._RESTORE_VERIFY_DELAYS,
                )
            except Exception as exc:
                self._record_uncertain_restore(
                    video_id=video_id,
                    before=before,
                    observed=current,
                    reason="restore_readback_failed",
                    restore_writes=restore_write,
                    verification_attempts=total_verification_attempts,
                )
                raise tool_error(
                    "write_state_uncertain",
                    "A restauração foi enviada, mas a releitura de confirmação falhou. O vídeo foi protegido contra novas escritas automáticas.",
                ) from exc

            total_verification_attempts += attempts
            last_observed = restored
            last_mismatches = mismatches
            last_exact = exact_differences
            self._log_partial_state(
                video_id=video_id,
                before=before,
                expected=expected,
                observed=restored,
                phase=f"restore_attempt_{restore_write}",
                verification_attempts=attempts,
            )

            if not mismatches:
                return restored, mismatches, exact_differences, total_verification_attempts

            states = self._provider_field_states(before=before, expected=expected, observed=restored)
            if "other" in states.values():
                self._record_uncertain_restore(
                    video_id=video_id,
                    before=before,
                    observed=restored,
                    reason="restore_readback_third_value",
                    restore_writes=restore_write,
                    verification_attempts=total_verification_attempts,
                )
                raise tool_error(
                    "write_state_uncertain",
                    "A restauração encontrou um valor externo ao snapshot/proposta assinados. O vídeo foi protegido e nenhuma nova compensação será enviada.",
                ) from restore_error

            if restore_write < self._MAX_RESTORE_WRITES:
                continue

            # The provider can expose the compensating write field-by-field
            # for several seconds. Before declaring rollback_incomplete, spend a
            # final bounded window on authoritative READBACK only. This never
            # retries the user's original write or sends another compensation.
            try:
                settled, settle_mismatches, settle_exact, settle_attempts = self._wait_for_snippet(
                    video_id,
                    before,
                    self._ROLLBACK_SETTLE_VERIFY_DELAYS,
                )
            except Exception as exc:
                self._record_uncertain_restore(
                    video_id=video_id,
                    before=before,
                    observed=restored,
                    reason="restore_settle_read_failed",
                    restore_writes=restore_write,
                    verification_attempts=total_verification_attempts,
                )
                raise tool_error(
                    "write_state_uncertain",
                    "O rollback foi enviado, mas a janela final de confirmação por leitura falhou. O vídeo foi protegido contra novas escritas automáticas.",
                ) from exc

            total_verification_attempts += settle_attempts
            self._log_partial_state(
                video_id=video_id,
                before=before,
                expected=expected,
                observed=settled,
                phase="restore_settle",
                verification_attempts=settle_attempts,
            )
            if not settle_mismatches:
                return settled, [], settle_exact, total_verification_attempts

            settle_states = self._provider_field_states(
                before=before,
                expected=expected,
                observed=settled,
            )
            if "other" in settle_states.values():
                self._record_uncertain_restore(
                    video_id=video_id,
                    before=before,
                    observed=settled,
                    reason="restore_settle_third_value",
                    restore_writes=restore_write,
                    verification_attempts=total_verification_attempts,
                )
                raise tool_error(
                    "write_state_uncertain",
                    "A janela final de confirmação encontrou um valor externo ao snapshot/proposta assinados. O vídeo foi protegido e nenhuma nova escrita será enviada.",
                ) from restore_error

            self._record_uncertain_restore(
                video_id=video_id,
                before=before,
                observed=settled,
                reason="restore_budget_exhausted",
                restore_writes=restore_write,
                verification_attempts=total_verification_attempts,
            )
            report = self._verification_report(expected=before, observed=settled)
            raise tool_error(
                "rollback_incomplete",
                "Foi detectada uma gravação parcial e, mesmo após a janela final somente de leitura, o rollback não restaurou todos os campos. O estado real foi relido e o vídeo foi protegido contra novas escritas automáticas.",
                details=report,
            ) from restore_error

        return last_observed, last_mismatches, last_exact, total_verification_attempts

    def _partial_write_error(
        self,
        *,
        write_verification: dict[str, Any],
        rollback: dict[str, Any],
    ) -> Exception:
        return tool_error(
            "partial_write_detected",
            "O YouTube persistiu apenas parte dos metadados aprovados. A ferramenta restaurou e verificou o snapshot anterior; gere uma nova prévia antes de tentar novamente.",
            details={
                "state": "partial_write_detected_and_restored",
                "write_verification": write_verification,
                "rollback": rollback,
            },
        )

    def _restore_then_raise_partial(
        self,
        *,
        video_id: str,
        before: dict[str, Any],
        expected: dict[str, Any],
        observed_after_write: dict[str, Any],
        verification_attempts: int,
        elapsed_ms: int,
        original_error: Exception | None = None,
    ) -> None:
        write_verification = self._verification_report(expected=expected, observed=observed_after_write)
        write_verification["observed_snapshot_after_write"] = dict(write_verification["observed_snapshot"])
        write_verification["verification_attempts"] = verification_attempts
        write_verification["elapsed_ms"] = elapsed_ms
        try:
            restored, _mismatches, _exact, rollback_attempts = self._restore_verified_snapshot(
                video_id=video_id,
                before=before,
                expected=expected,
            )
        except CreatorToolError as exc:
            if exc.code == "rollback_incomplete":
                raise tool_error(
                    "rollback_incomplete",
                    exc.message,
                    details={
                        "state": "partial_write_detected_and_rollback_incomplete",
                        "write_verification": write_verification,
                        "rollback": exc.details or {},
                    },
                ) from exc
            raise
        rollback = self._verification_report(expected=before, observed=restored)
        rollback["verification_attempts"] = rollback_attempts
        rollback["state"] = "restored_and_verified"
        raise self._partial_write_error(
            write_verification=write_verification,
            rollback=rollback,
        ) from original_error

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
            "state": "success_verified",
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
            self._log_partial_state(
                video_id=video_id,
                before=before,
                expected=expected,
                observed=observed,
                phase="ambiguous_response",
                verification_attempts=attempts,
            )
            self._restore_then_raise_partial(
                video_id=video_id,
                before=before,
                expected=expected,
                observed_after_write=observed,
                verification_attempts=attempts,
                elapsed_ms=int((time.monotonic() - write_verify_started) * 1000),
                original_error=original_error,
            )

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
        before, before_etag = self._versioned_video_snippet(video_id)
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

        # Defensive pre-validation runs after signature verification and before
        # any videos.update mutation. YouTube remains the final authority.
        metadata_validation = self.validate_youtube_metadata_limits(
            expected,
            category_explicit="categoryId" in proposed,
            default_language_explicit="defaultLanguage" in proposed,
        )

        snippet = self._snippet_for_update(expected)
        write_verify_started = time.monotonic()
        try:
            self._conditional_snippet_update(
                video_id=video_id,
                snippet=snippet,
                etag=before_etag,
            )
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
                self._log_partial_state(
                    video_id=video_id,
                    before=before,
                    expected=expected,
                    observed=observed,
                    phase="verification_exception",
                )
                self._restore_then_raise_partial(
                    video_id=video_id,
                    before=before,
                    expected=expected,
                    observed_after_write=observed,
                    verification_attempts=1,
                    elapsed_ms=int((time.monotonic() - write_verify_started) * 1000),
                    original_error=exc,
                )
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
            self._log_partial_state(
                video_id=video_id,
                before=before,
                expected=expected,
                observed=persisted,
                phase="confirmed_response",
                verification_attempts=attempts,
            )
            self._restore_then_raise_partial(
                video_id=video_id,
                before=before,
                expected=expected,
                observed_after_write=persisted,
                verification_attempts=attempts,
                elapsed_ms=int((time.monotonic() - write_verify_started) * 1000),
            )

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
