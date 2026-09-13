from __future__ import annotations

import threading
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

from desktop_local_server import DesktopLocalRuntime, LocalYouTubeClient
from elite_v2_ai_runtime import EliteV2AIError, EliteV2AIRuntime, proposal_payload
from elite_v2_automation import SupervisedAutomationQueue
from elite_v2_orchestrator import AIProvider
from elite_v2_ownership import (
    require_owned_playlist,
    require_owned_playlist_item,
    require_owned_video,
    require_proposal_ownership,
)
from elite_v2_server import EliteV2ProductHandler
from elite_v2_write_gateway import SafeWriteGateway, WriteProposal
from elite_v2_youtube_writes import ManualWriteSessionGate


class EliteV2FinalHandler(EliteV2ProductHandler):
    """Final local-first V2 surface with ownership, AI proposals and supervised queue."""

    @property
    def automation_queue(self) -> SupervisedAutomationQueue:
        return self.server.automation_queue  # type: ignore[attr-defined]

    @property
    def ai_runtime(self) -> EliteV2AIRuntime:
        return self.server.ai_runtime  # type: ignore[attr-defined]

    def _enforce_preview_ownership(self, payload: dict) -> None:
        action = str(payload.get("action") or "").strip().lower()
        client = LocalYouTubeClient()
        if action in {"video_privacy", "video_delete", "thumbnail_replace"}:
            require_owned_video(client, str(payload.get("video_id") or ""))
        elif action in {"playlist_update", "playlist_delete", "playlist_item_add"}:
            require_owned_playlist(client, str(payload.get("playlist_id") or ""))
        elif action in {"playlist_item_remove", "playlist_item_reorder"}:
            require_owned_playlist(client, str(payload.get("playlist_id") or ""))
            require_owned_playlist_item(client, str(payload.get("playlist_item_id") or ""))
        elif action == "playlist_create":
            # New playlists are created on the currently authorized channel.
            client.channel_identity()

    def _preview_management(self, payload: dict) -> dict:
        self._enforce_preview_ownership(payload)
        return super()._preview_management(payload)

    def _management_adapter(self, proposal: WriteProposal, payload: dict | None = None):
        client = LocalYouTubeClient()
        require_proposal_ownership(
            client,
            proposal.target_kind,
            proposal.target_id,
            proposal.operation,
            proposal.proposed,
        )
        # Parent creates a fresh client intentionally. Ownership was revalidated
        # immediately before adapter selection, protecting against account swaps
        # between preview and apply without sharing mutable auth state.
        return super()._management_adapter(proposal, payload)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/v2/ai/status":
            try:
                self._json(
                    HTTPStatus.OK,
                    {
                        "providers": self.ai_runtime.statuses(),
                        "execution_policy": "proposal_only",
                        "youtube_write_performed": False,
                    },
                )
            except Exception as exc:
                self._json(
                    HTTPStatus.OK,
                    {
                        "providers": [],
                        "execution_policy": "proposal_only",
                        "error": str(exc)[:500],
                        "youtube_write_performed": False,
                    },
                )
            return
        if parsed.path == "/api/v2/automation":
            limit = max(1, min(int(self._query(parsed, "limit", "100") or 100), 500))
            items = [row.public_payload() for row in self.automation_queue.list(limit=limit)]
            self._json(
                HTTPStatus.OK,
                {
                    "items": items,
                    "count": len(items),
                    "policy": "approval_required_then_write_gateway",
                    "youtube_write_performed": False,
                },
            )
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/v2/ai/propose":
                payload = self._read_json_body(max_bytes=500_000)
                provider = AIProvider(str(payload.get("provider") or "internal"))
                command = str(payload.get("command") or "")
                context = payload.get("context") or {}
                if not isinstance(context, dict):
                    raise ValueError("context deve ser objeto JSON")
                proposal = self.ai_runtime.propose(provider=provider, command=command, context=context)
                result = proposal_payload(proposal)
                if payload.get("enqueue") is True:
                    item = self.automation_queue.enqueue(
                        intent=proposal.intent.value,
                        provider=proposal.provider.value,
                        proposal=proposal.proposed_changes,
                        facts=proposal.facts,
                        target_kind=str(context.get("target_kind") or "") or None,
                        target_id=str(context.get("target_id") or context.get("video_id") or "") or None,
                    )
                    result["automation_item"] = item.public_payload()
                self._json(HTTPStatus.OK, result)
                return

            if path.startswith("/api/v2/automation/approve/"):
                payload = self._read_json_body(max_bytes=10_000)
                item_id = path.rsplit("/", 1)[-1]
                item = self.automation_queue.approve(item_id, user_confirmed=payload.get("confirmed") is True)
                self._json(
                    HTTPStatus.OK,
                    {"item": item.public_payload(), "youtube_write_performed": False},
                )
                return

            if path.startswith("/api/v2/automation/cancel/"):
                item_id = path.rsplit("/", 1)[-1]
                item = self.automation_queue.cancel(item_id)
                self._json(
                    HTTPStatus.OK,
                    {"item": item.public_payload(), "youtube_write_performed": False},
                )
                return

            if path.startswith("/api/v2/automation/handoff/"):
                payload = self._read_json_body(max_bytes=10_000)
                item_id = path.rsplit("/", 1)[-1]
                item = self.automation_queue.hand_to_write_gateway(
                    item_id,
                    user_confirmed=payload.get("confirmed") is True,
                )
                self._json(
                    HTTPStatus.OK,
                    {
                        "item": item.public_payload(),
                        "next_step": "create_write_gateway_preview",
                        "auto_apply": False,
                        "youtube_write_performed": False,
                    },
                )
                return

            super().do_POST()
        except (EliteV2AIError, ValueError, KeyError, PermissionError, RuntimeError) as exc:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"detail": str(exc)[:500], "youtube_write_performed": False},
            )


class EliteV2FinalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], runtime: DesktopLocalRuntime) -> None:
        super().__init__(address, EliteV2FinalHandler)
        self.runtime = runtime
        self.write_gateway = SafeWriteGateway()
        self.write_gate = ManualWriteSessionGate()
        self.approval_tokens: dict[str, str] = {}
        self.thumbnail_previews: dict[str, dict] = {}
        self.automation_queue = SupervisedAutomationQueue()
        self.ai_runtime = EliteV2AIRuntime()


def start_elite_v2_final_server() -> tuple[EliteV2FinalServer, threading.Thread, str]:
    runtime = DesktopLocalRuntime()
    server = EliteV2FinalServer(("127.0.0.1", 0), runtime)
    thread = threading.Thread(target=server.serve_forever, name="yca-elite-v2-final", daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"
