from __future__ import annotations

import json
import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from intelligence.channel_audit import ChannelAuditEngine
from intelligence.channel_command_center import ChannelCommandCenterEngine
from intelligence.channel_learning import ChannelLearningEngine
from intelligence.continuous_strategy import ContinuousStrategyEngine, StrategyHistoryStore
from intelligence.youtube_research import YouTubeResearchEngine

from .context import CreatorContext
from .tenant_store import TenantCredentialStore, TenantDatabase, tenant_database_from_env, validate_tenant_id


GOOGLE_SECRET_NAME = "google:authorized_user_json"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


class InjectedChannelCommandCenterEngine(ChannelCommandCenterEngine):
    """Command Center wired to already-authenticated Google clients."""

    def __init__(self, token_file: str, ai_runtime, youtube_client, analytics_client):
        self.token_file = token_file
        self.ai_runtime = ai_runtime
        self.learning = ChannelLearningEngine(
            token_file,
            youtube_client=youtube_client,
            analytics_client=analytics_client,
        )
        self.research = YouTubeResearchEngine(token_file, youtube_client=youtube_client)
        self.audit_engine = ChannelAuditEngine(
            token_file,
            ai_runtime,
            youtube_client=youtube_client,
            analytics_client=analytics_client,
        )


class InjectedContinuousStrategyEngine(ContinuousStrategyEngine):
    def __init__(
        self,
        token_file: str,
        ai_runtime,
        *,
        history_file: str | Path,
        youtube_client,
        analytics_client,
    ):
        self.token_file = token_file
        self.ai_runtime = ai_runtime
        self.store = StrategyHistoryStore(history_file)
        self.command = InjectedChannelCommandCenterEngine(
            token_file,
            ai_runtime,
            youtube_client,
            analytics_client,
        )


class CloudTenantResolver:
    """Resolves authenticated tenants without writing OAuth tokens to disk."""

    def __init__(self, root: str | Path | None = None, db: TenantDatabase | None = None):
        root = root or os.environ.get("YCA_ROOT") or Path(__file__).resolve().parents[2]
        self.root = Path(root).resolve()
        self.db = db or tenant_database_from_env(self.root)

    def _google_clients(self, tenant_id: str):
        raw = self.db.get_secret(tenant_id, GOOGLE_SECRET_NAME)
        if not raw:
            raise RuntimeError("Canal do YouTube ainda não conectado para este cliente.")
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Credencial Google armazenada está corrompida.") from exc
        creds = Credentials.from_authorized_user_info(info, GOOGLE_SCOPES)
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
        return youtube, analytics

    def resolve(self, tenant_id: str) -> CreatorContext:
        tenant_id = validate_tenant_id(tenant_id)
        self.db.ensure_tenant(tenant_id)
        tenant_dir = self.root / "data" / "tenants" / tenant_id
        tenant_dir.mkdir(parents=True, exist_ok=True)
        settings_file = tenant_dir / "ai_settings.json"
        has_google = self.db.get_secret(tenant_id, GOOGLE_SECRET_NAME) is not None
        return CreatorContext(
            tenant_id=tenant_id,
            token_file=tenant_dir / "__encrypted_google_credentials__",
            ai_settings_file=settings_file,
            data_dir=tenant_dir,
            credential_store=TenantCredentialStore(self.db, tenant_id),
            google_client_factory=lambda: self._google_clients(tenant_id),
            youtube_connected_override=has_google,
        )
