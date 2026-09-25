from __future__ import annotations

import base64
import hashlib
import threading
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from urllib.parse import unquote, urlparse
from uuid import uuid4

from desktop_local_server import DesktopLocalRuntime, LocalYouTubeClient, credentials_path
from elite_v2_analytics import EliteV2Handler
from elite_v2_management import (
    CAPABILITY_MATRIX,
    PlaylistItemAdapter,
    PlaylistMetadataAdapter,
    ThumbnailAdapter,
    ThumbnailPayload,
    VideoDeleteAdapter,
    VideoPrivacyAdapter,
)
from elite_v2_seo import analyze_metadata_facts, build_seo_context
from elite_v2_write_gateway import ApprovalError, SafeWriteGateway, WriteProposal, WriteState
from elite_v2_youtube_writes import ManualWriteSessionGate, YouTubeVideoMetadataAdapter
from intelligence.free_reach_reporting import YouTubeReachReporting


class EliteV2ProductHandler(EliteV2Handler):
    """Product-level V2 routes layered over the stable local-first API."""

    def _management_adapter(self, proposal: WriteProposal, payload: dict | None = None):
        client = LocalYouTubeClient()
        if proposal.target_kind == "video" and proposal.operation == "update" and "privacy_status" in (proposal.proposed or {}):
            return VideoPrivacyAdapter(client)
        if proposal.target_kind == "video" and proposal.operation == "delete":
            return VideoDeleteAdapter(client)
        if proposal.target_kind == "playlist":
            return PlaylistMetadataAdapter(client)
        if proposal.target_kind == "playlist_item":
            return PlaylistItemAdapter(client)
        if proposal.target_kind == "thumbnail":
            data = payload or {}
            raw = str(data.get("content_base64") or "")
            if not raw:
                raise ValueError("content_base64 é obrigatório para aplicar thumbnail")
            try:
                content = base64.b64decode(raw, validate=True)
            except Exception as exc:
                raise ValueError("content_base64 inválido") from exc
            mime = str(data.get("mime_type") or "").lower()
            return ThumbnailAdapter(client, ThumbnailPayload(proposal.target_id, content, mime))
        if proposal.target_kind == "video" and proposal.operation == "update":
            return YouTubeVideoMetadataAdapter(client)
        raise ValueError(f"adapter não disponível para {proposal.target_kind}/{proposal.operation}")

    def _preview_management(self, payload: dict) -> dict:
        self._require_connected()
        action = str(payload.get("action") or "").strip().lower()
        client = LocalYouTubeClient()
        gateway = self.write_gateway
        idempotency = str(payload.get("idempotency_key") or f"{action}:{uuid4()}")

        if action == "video_privacy":
            video_id = str(payload.get("video_id") or "").strip()
            if not video_id:
                raise ValueError("video_id é obrigatório")
            adapter = VideoPrivacyAdapter(client)
            current = adapter.current_status(video_id)
            proposed = {"privacy_status": str(payload.get("privacy_status") or "").lower()}
            proposal, token = gateway.preview(
                idempotency_key=idempotency,
                target_kind="video",
                target_id=video_id,
                operation="update",
                current=current,
                proposed=proposed,
                reversible=True,
            )
        elif action == "video_delete":
            video_id = str(payload.get("video_id") or "").strip()
            if not video_id:
                raise ValueError("video_id é obrigatório")
            current = client.video_details(video_id)
            proposal, token = gateway.preview(
                idempotency_key=idempotency,
                target_kind="video",
                target_id=video_id,
                operation="delete",
                current={"id": video_id, "title": str((current.get("snippet") or {}).get("title") or "")},
                proposed=None,
                reversible=False,
            )
        elif action in {"playlist_create", "playlist_update", "playlist_delete"}:
            adapter = PlaylistMetadataAdapter(client)
            playlist_id = str(payload.get("playlist_id") or "").strip()
            operation = action.rsplit("_", 1)[-1]
            if operation != "create" and not playlist_id:
                raise ValueError("playlist_id é obrigatório")
            current = None if operation == "create" else adapter.current_metadata(playlist_id)
            if operation != "create" and current is None:
                raise ValueError("playlist não encontrada")
            proposed = None
            if operation != "delete":
                proposed = adapter.normalize(
                    {
                        "title": payload.get("title") if payload.get("title") is not None else (current or {}).get("title"),
                        "description": payload.get("description") if payload.get("description") is not None else (current or {}).get("description"),
                        "privacy_status": payload.get("privacy_status") if payload.get("privacy_status") is not None else (current or {}).get("privacy_status", "private"),
                    },
                    current,
                )
            proposal, token = gateway.preview(
                idempotency_key=idempotency,
                target_kind="playlist",
                target_id=playlist_id or "pending",
                operation=operation,
                current=(None if current is None else {k: current[k] for k in ("title", "description", "privacy_status")}),
                proposed=proposed,
                reversible=operation != "delete",
            )
        elif action in {"playlist_item_add", "playlist_item_remove", "playlist_item_reorder"}:
            adapter = PlaylistItemAdapter(client)
            playlist_id = str(payload.get("playlist_id") or "").strip()
            video_id = str(payload.get("video_id") or "").strip()
            item_id = str(payload.get("playlist_item_id") or "").strip()
            if not playlist_id:
                raise ValueError("playlist_id é obrigatório")
            if action == "playlist_item_add":
                if not video_id:
                    raise ValueError("video_id é obrigatório")
                proposed = {"playlist_id": playlist_id, "video_id": video_id, "position": int(payload.get("position") or 0)}
                proposal, token = gateway.preview(
                    idempotency_key=idempotency,
                    target_kind="playlist_item",
                    target_id="pending",
                    operation="create",
                    current=None,
                    proposed=proposed,
                    reversible=True,
                )
            else:
                if not item_id:
                    raise ValueError("playlist_item_id é obrigatório")
                current = adapter._find(playlist_id, item_id=item_id)  # noqa: SLF001 - same local safe-management module
                if current is None:
                    raise ValueError("item de playlist não encontrado")
                normalized = {k: current[k] for k in ("playlist_id", "video_id", "position")}
                if action == "playlist_item_remove":
                    proposal, token = gateway.preview(
                        idempotency_key=idempotency,
                        target_kind="playlist_item",
                        target_id=item_id,
                        operation="delete",
                        current=normalized,
                        proposed=None,
                        reversible=False,
                    )
                else:
                    proposed = {**normalized, "position": int(payload.get("position") or 0)}
                    proposal, token = gateway.preview(
                        idempotency_key=idempotency,
                        target_kind="playlist_item",
                        target_id=item_id,
                        operation="reorder",
                        current=normalized,
                        proposed=proposed,
                        reversible=True,
                    )
        elif action == "thumbnail_replace":
            video_id = str(payload.get("video_id") or "").strip()
            mime = str(payload.get("mime_type") or "").lower()
            size = int(payload.get("size_bytes") or 0)
            digest = str(payload.get("sha256") or "").lower()
            if not video_id:
                raise ValueError("video_id é obrigatório")
            if mime not in {"image/jpeg", "image/png"}:
                raise ValueError("thumbnail deve ser JPEG ou PNG")
            if size <= 0 or size > 2 * 1024 * 1024:
                raise ValueError("thumbnail deve ter entre 1 byte e 2 MB")
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("sha256 da thumbnail é obrigatório")
            proposal, token = gateway.preview(
                idempotency_key=idempotency,
                target_kind="thumbnail",
                target_id=video_id,
                operation="update",
                current={"thumbnail_confirmed": False},
                proposed={"thumbnail_confirmed": True},
                reversible=False,
                confirmation_phrase=f"SUBSTITUIR THUMBNAIL {video_id}",
            )
            self.server.thumbnail_previews[proposal.proposal_id] = {  # type: ignore[attr-defined]
                "mime_type": mime,
                "size_bytes": size,
                "sha256": digest,
            }
        else:
            raise ValueError(f"ação de gerenciamento não suportada: {action}")

        self.approval_tokens[proposal.proposal_id] = token
        return {
            **proposal.public_payload(),
            "action_id": proposal.proposal_id,
            "write_mode_enabled": self.write_gate.enabled,
            "youtube_write_performed": False,
        }

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/v2/activity":
            limit = max(1, min(int(self._query(parsed, "limit", "100") or 100), 500))
            events = list(reversed(self.write_gateway.audit[-limit:]))
            self._json(
                HTTPStatus.OK,
                {
                    "events": events,
                    "event_count": len(events),
                    "source": "local_write_gateway_audit",
                    "youtube_write_performed": False,
                },
            )
            return
        if path == "/api/v2/capabilities":
            self._json(
                HTTPStatus.OK,
                {
                    "capabilities": CAPABILITY_MATRIX,
                    "write_mode_enabled": self.write_gate.enabled,
                    "session_only": True,
                    "youtube_write_performed": False,
                },
            )
            return
        if path == "/api/v2/reporting/reach":
            try:
                if not self.runtime.connected():
                    self._json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {
                            "data_available": False,
                            "source": "youtube_reporting_api",
                            "estimated": False,
                            "detail": "YouTube não conectado neste computador.",
                            "writes_performed": 0,
                        },
                    )
                    return
                video_id = self._query(parsed, "video_id", None)
                result = YouTubeReachReporting(str(credentials_path())).fetch_latest(video_id=video_id or None)
                result["estimated"] = False
                result["on_demand_only"] = True
                result["youtube_write_performed"] = False
                self._json(HTTPStatus.OK, result)
            except Exception as exc:
                self._json(
                    HTTPStatus.OK,
                    {
                        "data_available": False,
                        "source": "youtube_reporting_api",
                        "estimated": False,
                        "on_demand_only": True,
                        "error": str(exc)[:500],
                        "writes_performed": 0,
                        "youtube_write_performed": False,
                    },
                )
            return
        if not path.startswith("/api/v2/seo/video/"):
            super().do_GET()
            return
        try:
            if not self.runtime.connected():
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "available": False,
                        "source": "youtube_data_api_metadata",
                        "estimated": False,
                        "detail": "YouTube não conectado neste computador.",
                    },
                )
                return
            video_id = unquote(path.rsplit("/", 1)[-1]).strip()
            if not video_id:
                raise ValueError("video_id é obrigatório")
            details = LocalYouTubeClient().video_details(video_id)
            snippet = details.get("snippet") or {}
            video = {
                "title": snippet.get("title") or "",
                "description": snippet.get("description") or "",
                "tags": snippet.get("tags") or [],
            }
            facts = analyze_metadata_facts(video)
            context = build_seo_context(video)
            self._json(
                HTTPStatus.OK,
                {
                    "available": True,
                    "video_id": video_id,
                    "analysis": facts,
                    "context": context,
                    "youtube_write_performed": False,
                },
            )
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"detail": str(exc), "youtube_write_performed": False})
        except Exception as exc:
            self._error(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/v2/manage/"):
            super().do_POST()
            return
        try:
            if path == "/api/v2/manage/preview":
                payload = self._read_json_body(max_bytes=100_000)
                result = self._preview_management(payload)
                self._json(HTTPStatus.OK, result)
                return

            if path.startswith("/api/v2/manage/apply/"):
                self._require_connected()
                if not self.write_gate.enabled:
                    self._json(
                        HTTPStatus.LOCKED,
                        {
                            "detail": "Gerenciamento manual está bloqueado nesta sessão.",
                            "write_mode_enabled": False,
                            "youtube_write_performed": False,
                        },
                    )
                    return
                payload = self._read_json_body(max_bytes=3_000_000)
                if payload.get("confirmed") is not True:
                    raise ApprovalError("confirmação explícita ausente")
                action_id = path.rsplit("/", 1)[-1]
                proposal = self.write_gateway.get(action_id)
                if proposal.target_kind == "thumbnail":
                    preview = self.server.thumbnail_previews.get(action_id)  # type: ignore[attr-defined]
                    if not preview:
                        raise ApprovalError("preview de thumbnail expirou")
                    raw = str(payload.get("content_base64") or "")
                    try:
                        content = base64.b64decode(raw, validate=True)
                    except Exception as exc:
                        raise ValueError("content_base64 inválido") from exc
                    if len(content) != int(preview["size_bytes"]):
                        raise ApprovalError("arquivo de thumbnail não corresponde ao tamanho aprovado")
                    if hashlib.sha256(content).hexdigest() != preview["sha256"]:
                        raise ApprovalError("arquivo de thumbnail não corresponde ao sha256 aprovado")
                    if str(payload.get("mime_type") or "").lower() != preview["mime_type"]:
                        raise ApprovalError("mime_type da thumbnail não corresponde ao preview")
                if proposal.state is WriteState.AWAITING_APPROVAL:
                    token = self.approval_tokens.pop(action_id, None)
                    if not token:
                        raise ApprovalError("token local de aprovação expirou")
                    self.write_gateway.approve(
                        action_id,
                        token,
                        confirmation_text=payload.get("confirmation_text"),
                    )
                adapter = self._management_adapter(proposal, payload)
                result = self.write_gateway.apply(action_id, adapter)
                self._json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "state": result.state.value,
                        "target_id": result.target_id,
                        "readback_verified": result.state is WriteState.VERIFIED,
                        "rollback_available": result.reversible,
                        "youtube_write_actions_executed": int(getattr(adapter, "writes_performed", 0)),
                    },
                )
                return

            if path.startswith("/api/v2/manage/rollback/"):
                self._require_connected()
                if not self.write_gate.enabled:
                    self._json(HTTPStatus.LOCKED, {"detail": "Gerenciamento manual está bloqueado nesta sessão."})
                    return
                payload = self._read_json_body(max_bytes=10_000)
                if payload.get("confirmed") is not True:
                    raise ApprovalError("confirmação explícita ausente")
                action_id = path.rsplit("/", 1)[-1]
                proposal = self.write_gateway.get(action_id)
                adapter = self._management_adapter(proposal, payload)
                result = self.write_gateway.rollback(action_id, adapter)
                self._json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "state": result.state.value,
                        "youtube_write_actions_executed": int(getattr(adapter, "writes_performed", 0)),
                    },
                )
                return

            raise ValueError("rota de gerenciamento desconhecida")
        except PermissionError as exc:
            self._json(HTTPStatus.FORBIDDEN, {"detail": str(exc), "youtube_write_performed": False})
        except (ApprovalError, ValueError, KeyError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"detail": str(exc), "youtube_write_performed": False})
        except Exception as exc:
            self._error(exc)


class EliteV2ProductServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], runtime: DesktopLocalRuntime) -> None:
        super().__init__(address, EliteV2ProductHandler)
        self.runtime = runtime
        self.write_gateway = SafeWriteGateway()
        self.write_gate = ManualWriteSessionGate()
        self.approval_tokens: dict[str, str] = {}
        self.thumbnail_previews: dict[str, dict] = {}


def start_elite_v2_product_server() -> tuple[EliteV2ProductServer, threading.Thread, str]:
    runtime = DesktopLocalRuntime()
    server = EliteV2ProductServer(("127.0.0.1", 0), runtime)
    thread = threading.Thread(target=server.serve_forever, name="yca-elite-v2-product", daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"
