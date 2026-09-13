from __future__ import annotations

import threading
from copy import deepcopy
from typing import Any

from desktop_local_server import LocalYouTubeClient, YOUTUBE_API
from elite_v2_write_gateway import WriteProposal


class YouTubeWriteError(RuntimeError):
    pass


class ManualWriteSessionGate:
    """Explicit, in-memory opt-in for mutable YouTube actions.

    It resets to disabled every time the desktop application starts. Enabling it
    changes only local session policy; it does not itself call YouTube.
    """

    CONFIRMATION = "ATIVAR GERENCIAMENTO"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled = False

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_enabled(self, enabled: bool, *, confirmation: str | None = None) -> bool:
        with self._lock:
            if enabled and confirmation != self.CONFIRMATION:
                raise PermissionError("confirmação de gerenciamento inválida")
            self._enabled = bool(enabled)
            return self._enabled


class YouTubeVideoMetadataAdapter:
    """Concrete adapter for video snippet updates used only after gateway approval."""

    def __init__(self, client: LocalYouTubeClient) -> None:
        self.client = client
        self.writes_performed = 0

    def _request_json(self, method: str, url: str, *, params: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        response = self.client.session.request(method, url, params=params, json=body, timeout=8)
        if response.status_code == 401:
            raise YouTubeWriteError("Autorização do YouTube expirou. Reconecte o canal.")
        try:
            payload = response.json() if response.content else {}
        except Exception as exc:
            raise YouTubeWriteError(f"Resposta inválida da API do YouTube: HTTP {response.status_code}") from exc
        if not response.ok:
            message = ((payload.get("error") or {}).get("message")) if isinstance(payload, dict) else None
            raise YouTubeWriteError(message or f"YouTube API HTTP {response.status_code}")
        self.writes_performed += 1
        return payload

    def current_metadata(self, video_id: str) -> dict[str, Any]:
        details = self.client.video_details(video_id)
        snippet = details.get("snippet") or {}
        return {
            "title": snippet.get("title") or "",
            "description": snippet.get("description") or "",
            "tags": list(snippet.get("tags") or []),
        }

    def _update_metadata(self, video_id: str, desired: dict[str, Any]) -> None:
        details = self.client.video_details(video_id)
        snippet = details.get("snippet") or {}
        category_id = snippet.get("categoryId")
        if not category_id:
            raise YouTubeWriteError("categoryId atual não foi retornado; atualização bloqueada para evitar perda de metadados")
        updated = {
            "title": desired.get("title", snippet.get("title") or ""),
            "description": desired.get("description", snippet.get("description") or ""),
            "categoryId": str(category_id),
            "tags": list(desired.get("tags", snippet.get("tags") or [])),
        }
        for optional in ("defaultLanguage", "defaultAudioLanguage"):
            if snippet.get(optional):
                updated[optional] = snippet[optional]
        self._request_json(
            "PUT",
            f"{YOUTUBE_API}/videos",
            params={"part": "snippet"},
            body={"id": video_id, "snippet": updated},
        )

    def apply(self, proposal: WriteProposal) -> None:
        if proposal.target_kind != "video" or proposal.operation != "update":
            raise YouTubeWriteError("adapter de metadados aceita apenas update de vídeo")
        self._update_metadata(proposal.target_id, deepcopy(proposal.proposed or {}))

    def readback(self, proposal: WriteProposal) -> dict[str, Any] | None:
        return self.current_metadata(proposal.target_id)

    def rollback(self, proposal: WriteProposal, snapshot: dict[str, Any] | None) -> None:
        if snapshot is None:
            raise YouTubeWriteError("snapshot de rollback ausente")
        self._update_metadata(proposal.target_id, deepcopy(snapshot))
