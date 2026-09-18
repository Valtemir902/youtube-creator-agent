from __future__ import annotations

from types import SimpleNamespace

from creator_service.advanced_service import AdvancedSafeCreatorService
from creator_service.mcp_errors import CreatorToolError
from creator_service.security import ApprovalTokenSigner
import creator_service.cloud_mcp_server_management as management


SECRET = "0123456789abcdef0123456789abcdef"


class _Request:
    def __init__(self, fn):
        self.fn = fn
        self.headers: dict[str, str] = {}

    def execute(self):
        return self.fn(self)


class _Channels:
    def __init__(self, owner):
        self.owner = owner

    def list(self, *, part: str, mine: bool):
        assert part == "id"
        assert mine is True
        return _Request(lambda _request: {"items": [{"id": self.owner.authorized_channel_id}]})


class _Videos:
    def __init__(self, owner):
        self.owner = owner

    def list(self, *, part: str, id: str):
        assert id == self.owner.video_id

        def read(_request):
            if self.owner.deleted:
                return {"items": []}
            item = {
                "id": self.owner.video_id,
                "etag": self.owner.etag,
                "snippet": dict(self.owner.snippet),
            }
            if "status" in part:
                item["status"] = dict(self.owner.status)
            return {"items": [item]}

        return _Request(read)

    def update(self, *, part: str, body: dict):
        assert part == "status"
        assert body["id"] == self.owner.video_id
        assert set(body) == {"id", "status"}
        self.owner.last_update_body = body

        def apply(request):
            self.owner.update_calls += 1
            if request.headers.get("If-Match") != self.owner.etag:
                raise RuntimeError("stale etag")
            self.owner.status = dict(body["status"])
            self.owner.etag = f"etag-{self.owner.update_calls + 1}"
            return {"id": self.owner.video_id, "status": dict(self.owner.status)}

        return _Request(apply)

    def delete(self, *, id: str):
        assert id == self.owner.video_id

        def delete(_request):
            self.owner.delete_calls += 1
            if self.owner.delete_mode == "fails_before_delete":
                raise RuntimeError("provider rejected delete")
            self.owner.deleted = True
            if self.owner.delete_mode == "accepted_then_transport_failed":
                raise RuntimeError("connection reset after delete accepted")
            return None

        return _Request(delete)


class _Youtube:
    def __init__(
        self,
        *,
        owner_channel_id: str = "channel-1",
        authorized_channel_id: str = "channel-1",
        delete_mode: str = "success",
    ):
        self.video_id = "video-1"
        self.authorized_channel_id = authorized_channel_id
        self.deleted = False
        self.etag = "etag-1"
        self.snippet = {
            "channelId": owner_channel_id,
            "title": "Dark Country Test",
            "description": "Original description",
            "tags": ["dark country", "western"],
            "categoryId": "10",
            "defaultLanguage": "en",
            "publishedAt": "2026-01-01T00:00:00Z",
        }
        self.status = {
            "privacyStatus": "public",
            "license": "youtube",
            "embeddable": True,
            "publicStatsViewable": True,
            "selfDeclaredMadeForKids": False,
        }
        self.update_calls = 0
        self.delete_calls = 0
        self.delete_mode = delete_mode
        self.last_update_body = None
        self._channels = _Channels(self)
        self._videos = _Videos(self)

    def channels(self):
        return self._channels

    def videos(self):
        return self._videos


class _Service(AdvancedSafeCreatorService):
    def __init__(self, youtube):
        self.context = SimpleNamespace(tenant_id="tenant-1", validate_youtube=lambda: None)
        self.youtube = youtube
        self._authorized_channel_cache = None

    def _youtube(self):
        return self.youtube


def _assert_creator_error(fn, code: str):
    try:
        fn()
    except CreatorToolError as exc:
        assert exc.code == code
        return
    raise AssertionError(f"Expected CreatorToolError({code})")


def test_privacy_preview_is_read_only_and_signed(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    youtube = _Youtube()
    service = _Service(youtube)

    result = service.preview_video_privacy_update(video_id="video-1", privacy_status="unlisted")

    assert youtube.update_calls == 0
    assert youtube.delete_calls == 0
    assert result["current"]["privacy_status"] == "public"
    assert result["proposed"]["privacy_status"] == "unlisted"
    assert result["changed"] is True
    assert result["requires_explicit_user_confirmation"] is True
    assert result["approval_payload"]["baseline_digest"]


def test_privacy_apply_changes_only_privacy_and_preserves_other_fields(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    youtube = _Youtube()
    service = _Service(youtube)
    before_snippet = dict(youtube.snippet)
    before_status = dict(youtube.status)

    preview = service.preview_video_privacy_update(video_id="video-1", privacy_status="private")
    result = service.apply_video_privacy_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    assert result["persisted_verified"] is True
    assert result["current"]["privacy_status"] == "private"
    assert youtube.update_calls == 1
    assert youtube.snippet == before_snippet
    assert youtube.status["privacyStatus"] == "private"
    for field in ("license", "embeddable", "publicStatsViewable", "selfDeclaredMadeForKids"):
        assert youtube.status[field] == before_status[field]
    assert set(youtube.last_update_body) == {"id", "status"}
    assert "snippet" not in youtube.last_update_body

    rollback = result["rollback_preview"]
    restored = service.apply_video_privacy_update(
        approval_payload=rollback["rollback_payload"],
        approval_token=rollback["rollback_token"],
    )
    assert restored["persisted_verified"] is True
    assert youtube.status["privacyStatus"] == "public"
    assert youtube.update_calls == 2


def test_privacy_apply_blocks_divergent_baseline(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    youtube = _Youtube()
    service = _Service(youtube)
    preview = service.preview_video_privacy_update(video_id="video-1", privacy_status="private")
    youtube.snippet["title"] = "Concurrent external title"

    _assert_creator_error(
        lambda: service.apply_video_privacy_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        ),
        "external_change_detected",
    )
    assert youtube.update_calls == 0


def test_privacy_apply_rejects_expired_token(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    youtube = _Youtube()
    service = _Service(youtube)
    preview = service.preview_video_privacy_update(video_id="video-1", privacy_status="private")
    expired = ApprovalTokenSigner(SECRET).issue(
        "update_video_privacy",
        "video-1",
        preview["approval_payload"],
        now=1,
    )
    try:
        service.apply_video_privacy_update(
            approval_payload=preview["approval_payload"],
            approval_token=expired,
        )
    except ValueError as exc:
        assert "expired" in str(exc).lower()
    else:
        raise AssertionError("Expected expired token rejection")
    assert youtube.update_calls == 0


def test_video_control_ownership_is_enforced(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    service = _Service(_Youtube(owner_channel_id="foreign-channel"))

    _assert_creator_error(
        lambda: service.preview_video_privacy_update(video_id="video-1", privacy_status="private"),
        "video_not_owned",
    )
    _assert_creator_error(
        lambda: service.preview_video_delete(video_id="video-1"),
        "video_not_owned",
    )


def test_delete_preview_is_read_only_and_explicitly_irreversible(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    youtube = _Youtube()
    service = _Service(youtube)

    preview = service.preview_video_delete(video_id="video-1")

    assert youtube.delete_calls == 0
    assert preview["snapshot"]["title"] == "Dark Country Test"
    assert preview["snapshot"]["privacy_status"] == "public"
    assert preview["irreversible"] is True
    assert preview["rollback_supported"] is False
    assert preview["requires_explicit_user_confirmation"] is True


def test_delete_blocks_divergent_baseline(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    youtube = _Youtube()
    service = _Service(youtube)
    preview = service.preview_video_delete(video_id="video-1")
    youtube.status["privacyStatus"] = "unlisted"

    _assert_creator_error(
        lambda: service.apply_video_delete(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        ),
        "external_change_detected",
    )
    assert youtube.delete_calls == 0
    assert youtube.deleted is False


def test_delete_is_executed_once_and_verified_by_absence(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    youtube = _Youtube()
    service = _Service(youtube)
    preview = service.preview_video_delete(video_id="video-1")

    result = service.apply_video_delete(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    assert result["deleted_verified"] is True
    assert result["rollback_supported"] is False
    assert result["recovered_from_ambiguous_response"] is False
    assert youtube.delete_calls == 1
    assert youtube.deleted is True


def test_delete_ambiguous_response_uses_readback_without_retry(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    youtube = _Youtube(delete_mode="accepted_then_transport_failed")
    service = _Service(youtube)
    preview = service.preview_video_delete(video_id="video-1")

    result = service.apply_video_delete(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    assert result["deleted_verified"] is True
    assert result["recovered_from_ambiguous_response"] is True
    assert youtube.delete_calls == 1


def test_delete_failure_confirmed_existing_does_not_retry(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    youtube = _Youtube(delete_mode="fails_before_delete")
    service = _Service(youtube)
    preview = service.preview_video_delete(video_id="video-1")

    _assert_creator_error(
        lambda: service.apply_video_delete(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        ),
        "youtube_api_error",
    )
    assert youtube.delete_calls == 1
    assert youtube.deleted is False


def test_video_control_replay_guard(monkeypatch):
    signer = ApprovalTokenSigner(SECRET)
    payload = {
        "baseline_digest": "baseline",
        "proposed": {"video_id": "video-1", "privacy_status": "private"},
    }
    token = signer.issue("update_video_privacy", "video-1", payload)

    class _Store:
        def __init__(self):
            self.used = False

        def consume_write_token(self, *_args, **_kwargs):
            if self.used:
                return False
            self.used = True
            return True

    store = _Store()
    monkeypatch.setattr(management, "signer_from_env", lambda: signer)
    monkeypatch.setattr(management.base, "_ops_store", lambda: store)
    monkeypatch.setattr(management.base, "_tenant_id", lambda: "tenant-1")

    management._consume_token(
        token=token,
        payload=payload,
        action="update_video_privacy",
        subject="video-1",
    )
    _assert_creator_error(
        lambda: management._consume_token(
            token=token,
            payload=payload,
            action="update_video_privacy",
            subject="video-1",
        ),
        "approval_replayed",
    )
