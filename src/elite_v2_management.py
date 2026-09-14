from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from desktop_local_server import LocalYouTubeClient, YOUTUBE_API
from elite_v2_write_gateway import WriteProposal
from elite_v2_youtube_writes import YouTubeWriteError

UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
PLAYLIST_PRIVACY = {"public", "unlisted", "private"}
VIDEO_PRIVACY = {"public", "unlisted", "private"}


def _json_response(response, *, allow_not_found: bool = False) -> dict[str, Any]:
    if allow_not_found and response.status_code == 404:
        return {}
    if response.status_code == 401:
        raise YouTubeWriteError("Autorização do YouTube expirou. Reconecte o canal.")
    try:
        payload = response.json() if response.content else {}
    except Exception as exc:
        raise YouTubeWriteError(f"Resposta inválida da API do YouTube: HTTP {response.status_code}") from exc
    if not response.ok:
        message = ((payload.get("error") or {}).get("message")) if isinstance(payload, dict) else None
        raise YouTubeWriteError(message or f"YouTube API HTTP {response.status_code}")
    return payload if isinstance(payload, dict) else {}


class _AdapterBase:
    def __init__(self, client: LocalYouTubeClient) -> None:
        self.client = client
        self.writes_performed = 0

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any]:
        response = self.client.session.request(
            method,
            url,
            params=params,
            json=json_body,
            data=data,
            headers=headers,
            timeout=8,
        )
        payload = _json_response(response, allow_not_found=allow_not_found)
        if response.ok and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            self.writes_performed += 1
        return payload


class VideoPrivacyAdapter(_AdapterBase):
    """Safely updates only video privacy while preserving editable status fields."""

    _PRESERVE = (
        "license",
        "embeddable",
        "publicStatsViewable",
        "publishAt",
        "selfDeclaredMadeForKids",
        "containsSyntheticMedia",
    )

    def current_status(self, video_id: str) -> dict[str, Any]:
        payload = self.client._get(f"{YOUTUBE_API}/videos", {"part": "status", "id": video_id})  # noqa: SLF001
        items = payload.get("items") or []
        if not items:
            raise YouTubeWriteError("Vídeo não encontrado ou não acessível pela conta conectada.")
        status = items[0].get("status") or {}
        return {"privacy_status": str(status.get("privacyStatus") or "private")}

    def apply(self, proposal: WriteProposal) -> None:
        if proposal.target_kind != "video" or proposal.operation != "update":
            raise YouTubeWriteError("adapter de privacidade aceita apenas update de vídeo")
        desired = str((proposal.proposed or {}).get("privacy_status") or "").lower()
        if desired not in VIDEO_PRIVACY:
            raise YouTubeWriteError("privacy_status inválido")
        raw = self.client._get(f"{YOUTUBE_API}/videos", {"part": "status", "id": proposal.target_id})  # noqa: SLF001
        items = raw.get("items") or []
        if not items:
            raise YouTubeWriteError("Vídeo não encontrado")
        current = items[0].get("status") or {}
        status: dict[str, Any] = {"privacyStatus": desired}
        for key in self._PRESERVE:
            if key in current and current.get(key) is not None:
                status[key] = current[key]
        self._request(
            "PUT",
            f"{YOUTUBE_API}/videos",
            params={"part": "status"},
            json_body={"id": proposal.target_id, "status": status},
        )

    def readback(self, proposal: WriteProposal) -> dict[str, Any] | None:
        return self.current_status(proposal.target_id)

    def rollback(self, proposal: WriteProposal, snapshot: dict[str, Any] | None) -> None:
        if snapshot is None:
            raise YouTubeWriteError("snapshot de rollback ausente")
        desired = str(snapshot.get("privacy_status") or "").lower()
        if desired not in VIDEO_PRIVACY:
            raise YouTubeWriteError("snapshot de privacidade inválido")
        rollback_proposal = deepcopy(proposal)
        rollback_proposal.proposed = {"privacy_status": desired}
        self.apply(rollback_proposal)


class VideoDeleteAdapter(_AdapterBase):
    """Irreversible video deletion. The gateway must require target-specific confirmation."""

    def apply(self, proposal: WriteProposal) -> None:
        if proposal.target_kind != "video" or proposal.operation != "delete":
            raise YouTubeWriteError("adapter de exclusão aceita apenas delete de vídeo")
        self._request("DELETE", f"{YOUTUBE_API}/videos", params={"id": proposal.target_id})

    def readback(self, proposal: WriteProposal) -> dict[str, Any] | None:
        payload = self.client._get(f"{YOUTUBE_API}/videos", {"part": "id", "id": proposal.target_id})  # noqa: SLF001
        return None if not (payload.get("items") or []) else {"id": proposal.target_id}

    def rollback(self, proposal: WriteProposal, snapshot: dict[str, Any] | None) -> None:
        raise YouTubeWriteError("exclusão de vídeo não oferece rollback pela API do YouTube")


class PlaylistMetadataAdapter(_AdapterBase):
    """Create/update/delete playlist metadata with readback verification."""

    def current_metadata(self, playlist_id: str) -> dict[str, Any] | None:
        payload = self.client._get(
            f"{YOUTUBE_API}/playlists",
            {"part": "snippet,status,contentDetails", "id": playlist_id, "maxResults": 1},
        )  # noqa: SLF001
        items = payload.get("items") or []
        if not items:
            return None
        item = items[0]
        snippet = item.get("snippet") or {}
        return {
            "playlist_id": str(item.get("id") or playlist_id),
            "title": str(snippet.get("title") or ""),
            "description": str(snippet.get("description") or ""),
            "privacy_status": str((item.get("status") or {}).get("privacyStatus") or "private"),
            "item_count": int((item.get("contentDetails") or {}).get("itemCount") or 0),
        }

    @staticmethod
    def normalize(proposed: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        current = current or {}
        title = str(proposed.get("title", current.get("title") or "")).strip()
        description = str(proposed.get("description", current.get("description") or "")).strip()
        privacy = str(proposed.get("privacy_status", current.get("privacy_status") or "private")).lower()
        if not title:
            raise YouTubeWriteError("título da playlist não pode ficar vazio")
        if len(title) > 150:
            raise YouTubeWriteError("título da playlist excede 150 caracteres")
        if len(description) > 5000:
            raise YouTubeWriteError("descrição da playlist excede 5.000 caracteres")
        if privacy not in PLAYLIST_PRIVACY:
            raise YouTubeWriteError("privacy_status da playlist inválido")
        return {"title": title, "description": description, "privacy_status": privacy}

    def apply(self, proposal: WriteProposal) -> None:
        if proposal.target_kind != "playlist":
            raise YouTubeWriteError("adapter de playlist recebeu target_kind inválido")
        if proposal.operation == "delete":
            self._request("DELETE", f"{YOUTUBE_API}/playlists", params={"id": proposal.target_id})
            return
        desired = self.normalize(proposal.proposed or {}, proposal.current)
        if proposal.operation == "update":
            self._request(
                "PUT",
                f"{YOUTUBE_API}/playlists",
                params={"part": "snippet,status"},
                json_body={
                    "id": proposal.target_id,
                    "snippet": {"title": desired["title"], "description": desired["description"]},
                    "status": {"privacyStatus": desired["privacy_status"]},
                },
            )
            return
        if proposal.operation == "create":
            created = self._request(
                "POST",
                f"{YOUTUBE_API}/playlists",
                params={"part": "snippet,status"},
                json_body={
                    "snippet": {"title": desired["title"], "description": desired["description"]},
                    "status": {"privacyStatus": desired["privacy_status"]},
                },
            )
            created_id = str(created.get("id") or "")
            if not created_id:
                raise YouTubeWriteError("YouTube não retornou playlist_id após criação")
            proposal.target_id = created_id
            return
        raise YouTubeWriteError(f"operação de playlist não suportada: {proposal.operation}")

    def readback(self, proposal: WriteProposal) -> dict[str, Any] | None:
        row = self.current_metadata(proposal.target_id)
        if row is None:
            return None
        return {
            "title": row["title"],
            "description": row["description"],
            "privacy_status": row["privacy_status"],
        }

    def rollback(self, proposal: WriteProposal, snapshot: dict[str, Any] | None) -> None:
        if proposal.operation == "create":
            self._request("DELETE", f"{YOUTUBE_API}/playlists", params={"id": proposal.target_id})
            return
        if snapshot is None:
            raise YouTubeWriteError("snapshot de rollback ausente")
        desired = self.normalize(snapshot)
        self._request(
            "PUT",
            f"{YOUTUBE_API}/playlists",
            params={"part": "snippet,status"},
            json_body={
                "id": proposal.target_id,
                "snippet": {"title": desired["title"], "description": desired["description"]},
                "status": {"privacyStatus": desired["privacy_status"]},
            },
        )


class PlaylistItemAdapter(_AdapterBase):
    """Add, remove and reposition playlist items with deterministic readback."""

    def _find(self, playlist_id: str, *, video_id: str | None = None, item_id: str | None = None) -> dict[str, Any] | None:
        params: dict[str, Any] = {"part": "snippet,contentDetails", "maxResults": 50}
        if item_id:
            params["id"] = item_id
        else:
            params["playlistId"] = playlist_id
        payload = self.client._get(f"{YOUTUBE_API}/playlistItems", params)  # noqa: SLF001
        for item in payload.get("items") or []:
            snippet = item.get("snippet") or {}
            current_video = str((item.get("contentDetails") or {}).get("videoId") or (snippet.get("resourceId") or {}).get("videoId") or "")
            if item_id and str(item.get("id") or "") != item_id:
                continue
            if video_id and current_video != video_id:
                continue
            return {
                "playlist_item_id": str(item.get("id") or ""),
                "playlist_id": str(snippet.get("playlistId") or playlist_id),
                "video_id": current_video,
                "position": int(snippet.get("position") or 0),
            }
        return None

    def apply(self, proposal: WriteProposal) -> None:
        data = proposal.proposed or {}
        if proposal.target_kind != "playlist_item":
            raise YouTubeWriteError("adapter de item recebeu target_kind inválido")
        if proposal.operation == "create":
            playlist_id = str(data.get("playlist_id") or "")
            video_id = str(data.get("video_id") or "")
            if not playlist_id or not video_id:
                raise YouTubeWriteError("playlist_id e video_id são obrigatórios")
            snippet: dict[str, Any] = {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
            if data.get("position") is not None:
                snippet["position"] = int(data["position"])
            created = self._request(
                "POST",
                f"{YOUTUBE_API}/playlistItems",
                params={"part": "snippet"},
                json_body={"snippet": snippet},
            )
            item_id = str(created.get("id") or "")
            if not item_id:
                raise YouTubeWriteError("YouTube não retornou playlist_item_id")
            proposal.target_id = item_id
            return
        if proposal.operation == "delete":
            self._request("DELETE", f"{YOUTUBE_API}/playlistItems", params={"id": proposal.target_id})
            return
        if proposal.operation == "reorder":
            playlist_id = str(data.get("playlist_id") or "")
            video_id = str(data.get("video_id") or "")
            position = int(data.get("position") or 0)
            if not playlist_id or not video_id:
                raise YouTubeWriteError("playlist_id e video_id são obrigatórios para reordenação")
            self._request(
                "PUT",
                f"{YOUTUBE_API}/playlistItems",
                params={"part": "snippet"},
                json_body={
                    "id": proposal.target_id,
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        "position": position,
                    },
                },
            )
            return
        raise YouTubeWriteError(f"operação de item não suportada: {proposal.operation}")

    def readback(self, proposal: WriteProposal) -> dict[str, Any] | None:
        if proposal.operation == "delete":
            return self._find("", item_id=proposal.target_id)
        found = self._find("", item_id=proposal.target_id)
        if found is None:
            return None
        return {
            "playlist_id": found["playlist_id"],
            "video_id": found["video_id"],
            "position": found["position"],
        }

    def rollback(self, proposal: WriteProposal, snapshot: dict[str, Any] | None) -> None:
        if proposal.operation == "create":
            self._request("DELETE", f"{YOUTUBE_API}/playlistItems", params={"id": proposal.target_id})
            return
        if proposal.operation == "reorder" and snapshot:
            rollback = deepcopy(proposal)
            rollback.proposed = deepcopy(snapshot)
            self.apply(rollback)
            return
        raise YouTubeWriteError("rollback automático não disponível para remoção de item")


@dataclass(slots=True)
class ThumbnailPayload:
    video_id: str
    content: bytes
    mime_type: str


class ThumbnailAdapter(_AdapterBase):
    """Replace a thumbnail after explicit approval. YouTube does not expose the old bytes for rollback."""

    def __init__(self, client: LocalYouTubeClient, payload: ThumbnailPayload) -> None:
        super().__init__(client)
        self.payload = payload
        self._api_confirmed = False

    def apply(self, proposal: WriteProposal) -> None:
        if proposal.target_kind != "thumbnail" or proposal.operation != "update":
            raise YouTubeWriteError("adapter de thumbnail recebeu operação inválida")
        if proposal.target_id != self.payload.video_id:
            raise YouTubeWriteError("video_id da thumbnail não corresponde ao preview aprovado")
        if not self.payload.content:
            raise YouTubeWriteError("arquivo de thumbnail vazio")
        if len(self.payload.content) > 2 * 1024 * 1024:
            raise YouTubeWriteError("thumbnail excede 2 MB")
        if self.payload.mime_type not in {"image/jpeg", "image/png"}:
            raise YouTubeWriteError("thumbnail deve ser JPEG ou PNG")
        payload = self._request(
            "POST",
            f"{UPLOAD_API}/thumbnails/set",
            params={"videoId": proposal.target_id, "uploadType": "media"},
            data=self.payload.content,
            headers={"Content-Type": self.payload.mime_type},
        )
        self._api_confirmed = bool(payload.get("items"))
        if not self._api_confirmed:
            raise YouTubeWriteError("YouTube não confirmou a atualização da thumbnail")

    def readback(self, proposal: WriteProposal) -> dict[str, Any] | None:
        payload = self.client._get(f"{YOUTUBE_API}/videos", {"part": "snippet", "id": proposal.target_id})  # noqa: SLF001
        items = payload.get("items") or []
        if not items:
            return None
        thumbnails = ((items[0].get("snippet") or {}).get("thumbnails") or {})
        return {"thumbnail_confirmed": bool(self._api_confirmed and thumbnails)}

    def rollback(self, proposal: WriteProposal, snapshot: dict[str, Any] | None) -> None:
        raise YouTubeWriteError("a API do YouTube não fornece os bytes da thumbnail anterior; rollback automático não é seguro")


CAPABILITY_MATRIX: dict[str, dict[str, Any]] = {
    "video_metadata": {"preview": True, "apply": True, "readback": True, "rollback": True, "destructive": False},
    "video_privacy": {"preview": True, "apply": True, "readback": True, "rollback": True, "destructive": False},
    "video_delete": {"preview": True, "apply": True, "readback": True, "rollback": False, "destructive": True},
    "playlist_metadata": {"preview": True, "apply": True, "readback": True, "rollback": True, "destructive": False},
    "playlist_delete": {"preview": True, "apply": True, "readback": True, "rollback": False, "destructive": True},
    "playlist_item_add": {"preview": True, "apply": True, "readback": True, "rollback": True, "destructive": False},
    "playlist_item_remove": {"preview": True, "apply": True, "readback": True, "rollback": False, "destructive": True},
    "playlist_item_reorder": {"preview": True, "apply": True, "readback": True, "rollback": True, "destructive": False},
    "thumbnail_replace": {"preview": True, "apply": True, "readback": True, "rollback": False, "destructive": False, "high_risk": True},
}
