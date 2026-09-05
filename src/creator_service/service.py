from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from ai.runtime import AIRuntime
from intelligence.channel_learning import ChannelLearningEngine
from intelligence.continuous_strategy import ContinuousStrategyEngine
from intelligence.strategy_engine import StrategyEngine
from publicador_youtube import PublicadorYouTube

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
        self.context = context
        self.ai_runtime = AIRuntime(context.ai_settings_file)

    def status(self) -> dict:
        settings = self.ai_runtime.load_settings()
        return {
            "tenant_id": self.context.tenant_id,
            "youtube_connected": self.context.token_file.exists(),
            "ai_configured": bool(settings.model),
            "ai_provider": settings.provider,
            "ai_model": settings.model,
        }

    def channel_profile(self, period_days: int = 28) -> dict:
        self.context.validate_readiness()
        days = max(7, min(90, int(period_days)))
        profile = ChannelLearningEngine(str(self.context.token_file)).collect(
            period_days=days,
            max_videos=50,
        )
        return _plain(profile)

    def research_topic(self, seed: str, candidate_limit: int = 8) -> dict:
        self.context.validate_readiness()
        report = StrategyEngine(
            str(self.context.token_file),
            self.ai_runtime,
            snapshot_db=self.context.data_dir / "channel_intelligence.sqlite3",
        ).build_report(seed, candidate_limit=max(3, min(12, int(candidate_limit))))
        return _plain(report)

    def build_channel_strategy(self) -> dict:
        self.context.validate_readiness()
        report = ContinuousStrategyEngine(
            str(self.context.token_file),
            self.ai_runtime,
            history_db=self.context.data_dir / "strategy_history.sqlite3",
        ).build()
        return _plain(report)

    def _youtube(self):
        return PublicadorYouTube(str(self.context.token_file)).obter_cliente_youtube()

    def _current_video_snippet(self, video_id: str) -> dict:
        video_id = video_id.strip()
        if not video_id:
            raise ValueError("video_id é obrigatório.")
        response = self._youtube().videos().list(
            part="snippet",
            id=video_id,
            mine=True,
        ).execute()
        items = response.get("items", [])
        if not items:
            # `mine` is not accepted in every videos.list combination. Fall back to
            # ID lookup, then ownership is still constrained at update time by OAuth.
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

    def preview_video_metadata_update(
        self,
        *,
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        self.context.validate_readiness()
        current = self._current_video_snippet(video_id)
        proposed = self._normalize_metadata_payload(
            video_id=video_id,
            title=title,
            description=description,
            tags=tags,
            current=current,
        )
        approval_token = signer_from_env().issue(
            "update_video_metadata",
            proposed["video_id"],
            proposed,
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
            "approval_token": approval_token,
            "expires_in_seconds": 900,
            "requires_explicit_user_confirmation": True,
        }

    def apply_video_metadata_update(self, *, proposed: dict, approval_token: str) -> dict:
        self.context.validate_readiness()
        video_id = str(proposed.get("video_id", "")).strip()
        if not video_id:
            raise ValueError("video_id ausente no payload aprovado.")

        current = self._current_video_snippet(video_id)
        normalized = self._normalize_metadata_payload(
            video_id=video_id,
            title=str(proposed.get("title", "")),
            description=str(proposed.get("description", "")),
            tags=list(proposed.get("tags", []) or []),
            current=current,
        )
        # Category/defaultLanguage are server-owned fields, not model-controlled.
        normalized["categoryId"] = current["categoryId"]
        normalized["defaultLanguage"] = current.get("defaultLanguage")

        signer_from_env().verify(
            approval_token,
            action="update_video_metadata",
            subject=video_id,
            payload=normalized,
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
                key for key in ("title", "description", "tags")
                if current.get(key) != normalized.get(key)
            ],
        }
