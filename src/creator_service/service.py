from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .context import CreatorContext
from .security import signer_from_env


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _clean_tags(tags: list[str] | None) -> list[str] | None:
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
        if len(clean) >= 12:
            break
    if sum(len(tag) + 1 for tag in clean) > 500:
        raise ValueError("As tags ultrapassam o limite total seguro de 500 caracteres.")
    return clean


class CreatorService:
    """UI-agnostic application service used by desktop, API and MCP surfaces."""

    def __init__(self, context: CreatorContext):
        from ai.runtime import AIRuntime

        self.context = context
        self.ai_runtime = AIRuntime(
            context.ai_settings_file,
            credential_store=context.credential_store,
        )

    def _clients(self):
        return self.context.google_clients()

    def status(self) -> dict:
        settings = self.ai_runtime.load_settings()
        external_ai_configured = bool(settings.model)
        return {
            "tenant_id": self.context.tenant_id,
            "youtube_connected": self.context.youtube_connected,
            "intelligence_mode": "chatgpt_native_or_standalone",
            "chatgpt_native_ready": bool(self.context.youtube_connected),
            "external_ai_optional_for_chatgpt": True,
            "external_ai_configured": external_ai_configured,
            "ai_provider": settings.provider,
            "ai_model": settings.model,
        }

    def chatgpt_capabilities(self) -> dict:
        from .native_mode import ChatGPTNativeEvidenceEngine

        return ChatGPTNativeEvidenceEngine(self.context).capabilities()

    def strategy_evidence(self, period_days: int = 28) -> dict:
        from .native_mode import ChatGPTNativeEvidenceEngine

        return ChatGPTNativeEvidenceEngine(self.context).strategy_evidence(period_days=period_days)

    def validate_keyword_candidates(
        self,
        keywords: list[str],
        *,
        period_days: int = 28,
        max_results: int = 25,
    ) -> dict:
        from .native_mode import ChatGPTNativeEvidenceEngine

        return ChatGPTNativeEvidenceEngine(self.context).validate_keywords(
            keywords,
            period_days=period_days,
            max_results=max_results,
        )

    def channel_profile(self, period_days: int = 28) -> dict:
        from intelligence.channel_learning import ChannelLearningEngine

        self.context.validate_youtube()
        youtube, analytics = self._clients()
        days = max(7, min(90, int(period_days)))
        profile = ChannelLearningEngine(
            str(self.context.token_file),
            youtube_client=youtube,
            analytics_client=analytics,
        ).collect(period_days=days, max_videos=50)
        return _plain(profile)

    def research_topic(self, seed: str, candidate_limit: int = 8) -> dict:
        """Standalone legacy strategy path using the configured external AI."""
        from intelligence.strategy_engine import StrategyEngine

        self.context.validate_readiness()
        youtube, analytics = self._clients()
        report = StrategyEngine(
            str(self.context.token_file),
            self.ai_runtime,
            snapshot_db=self.context.data_dir / "channel_intelligence.sqlite3",
            youtube_client=youtube,
            analytics_client=analytics,
        ).build_report(seed, candidate_limit=max(3, min(12, int(candidate_limit))))
        return _plain(report)

    def build_channel_strategy(self) -> dict:
        """Standalone legacy strategy path using the configured external AI."""
        self.context.validate_readiness()
        youtube, analytics = self._clients()
        history_file = self.context.data_dir / "strategy_history.sqlite3"
        if youtube is not None and analytics is not None:
            from .cloud_runtime import InjectedContinuousStrategyEngine

            engine = InjectedContinuousStrategyEngine(
                str(self.context.token_file),
                self.ai_runtime,
                history_file=history_file,
                youtube_client=youtube,
                analytics_client=analytics,
            )
        else:
            from intelligence.continuous_strategy import ContinuousStrategyEngine

            engine = ContinuousStrategyEngine(
                str(self.context.token_file),
                self.ai_runtime,
                history_file=history_file,
            )
        return _plain(engine.build())

    def _youtube(self):
        youtube, _ = self._clients()
        if youtube is not None:
            return youtube
        from publicador_youtube import PublicadorYouTube

        return PublicadorYouTube(str(self.context.token_file)).obter_cliente_youtube()

    def _current_video_snippet(self, video_id: str) -> dict:
        video_id = video_id.strip()
        if not video_id:
            raise ValueError("video_id é obrigatório.")
        response = self._youtube().videos().list(part="snippet", id=video_id).execute()
        items = response.get("items", [])
        if not items:
            raise ValueError("Vídeo não encontrado para a conta conectada.")
        snippet = items[0].get("snippet", {})
        return {
            "title": str(snippet.get("title", "")),
            "description": str(snippet.get("description", "")),
            "tags": list(snippet.get("tags", []) or []),
            "categoryId": str(snippet.get("categoryId", "22")),
            "defaultLanguage": snippet.get("defaultLanguage"),
        }

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
        clean_tags = _clean_tags(tags)
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
    def _approval_envelope(current: dict, proposed: dict) -> dict:
        signer = signer_from_env()
        return {"baseline_digest": signer.payload_digest(current), "proposed": proposed}

    def preview_video_metadata_update(
        self,
        *,
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        self.context.validate_youtube()
        current = self._current_video_snippet(video_id)
        proposed = self._normalize_metadata_payload(
            video_id=video_id,
            title=title,
            description=description,
            tags=tags,
            current=current,
        )
        envelope = self._approval_envelope(current, proposed)
        approval_token = signer_from_env().issue(
            "update_video_metadata",
            proposed["video_id"],
            envelope,
        )
        changed = {
            key: current.get(key) != proposed.get(key)
            for key in ("title", "description", "tags")
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
        }

    def apply_video_metadata_update(self, *, approval_payload: dict, approval_token: str) -> dict:
        self.context.validate_youtube()
        proposed = dict(approval_payload.get("proposed", {}) or {})
        video_id = str(proposed.get("video_id", "")).strip()
        if not video_id:
            raise ValueError("video_id ausente no payload aprovado.")
        current = self._current_video_snippet(video_id)
        baseline_digest = str(approval_payload.get("baseline_digest", ""))
        if not baseline_digest or baseline_digest != signer_from_env().payload_digest(current):
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
        signer_from_env().verify(
            approval_token,
            action="update_video_metadata",
            subject=video_id,
            payload=normalized_envelope,
        )
        snippet = {
            "title": normalized["title"],
            "description": normalized["description"],
            "tags": normalized["tags"],
            "categoryId": normalized["categoryId"],
        }
        if normalized.get("defaultLanguage"):
            snippet["defaultLanguage"] = normalized["defaultLanguage"]
        response = self._youtube().videos().update(
            part="snippet",
            body={"id": video_id, "snippet": snippet},
        ).execute()
        return {
            "ok": True,
            "video_id": video_id,
            "title": response.get("snippet", {}).get("title", normalized["title"]),
            "changed_fields": [
                key
                for key in ("title", "description", "tags")
                if current.get(key) != normalized.get(key)
            ],
        }
