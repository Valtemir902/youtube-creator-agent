from __future__ import annotations

import asyncio
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import requests
from mcp import Client
from PIL import Image

from creator_service import cloud_mcp_server as base_mcp
from creator_service import cloud_mcp_server_management as management
from creator_service.mcp_errors import CreatorToolError
from creator_service.publication_store import PublicationStore
from creator_service.security import ApprovalTokenSigner
from creator_service.thumbnail_staging import ThumbnailStagingStore
from creator_service.thumbnail_update import (
    THUMBNAIL_VERIFY_DELAYS,
    ThumbnailUpdateMixin,
    _canonical_https_url,
    _download_https_thumbnail,
    _inspect_image,
    _validate_public_host,
)
import creator_service.thumbnail_update as thumbnail_module


SECRET = "0123456789abcdef0123456789abcdef"


def _image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (1280, 720)) -> bytes:
    stream = io.BytesIO()
    mode = "RGB" if fmt == "JPEG" else "RGBA"
    image = Image.new(mode, size)
    image.save(stream, format=fmt)
    return stream.getvalue()


def _validation(data: bytes, *, url: str = "https://cdn.example.test/thumb.jpg") -> dict:
    result = _inspect_image(data, source_url=url, header_content_type="image/jpeg" if data[:2] == b"\xff\xd8" else "image/png")
    result["source_url_sha256"] = "test"
    result["redirect_count"] = 0
    result["final_url"] = url
    return result


def _assert_code(exc_info, code: str) -> CreatorToolError:
    exc = exc_info.value
    assert isinstance(exc, CreatorToolError)
    assert exc.code == code
    return exc


def test_valid_jpeg_is_accepted():
    data = _image_bytes("JPEG")
    result = _inspect_image(data, source_url="https://cdn.example.test/thumb.jpg", header_content_type="image/jpeg")
    assert result["thumbnail_valid"] is True
    assert result["mime_type"] == "image/jpeg"
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["aspect_ratio_recommended"] is True


def test_valid_png_is_accepted():
    data = _image_bytes("PNG")
    result = _inspect_image(data, source_url="https://cdn.example.test/thumb.png", header_content_type="image/png")
    assert result["thumbnail_valid"] is True
    assert result["mime_type"] == "image/png"


def test_oversized_file_is_rejected(monkeypatch):
    monkeypatch.setattr(thumbnail_module, "THUMBNAIL_MAX_SOURCE_BYTES", 10)
    with pytest.raises(CreatorToolError) as caught:
        _inspect_image(_image_bytes("JPEG"), source_url="https://cdn.example.test/thumb.jpg", header_content_type="image/jpeg")
    _assert_code(caught, "thumbnail_too_large")


def test_false_mime_header_is_rejected():
    data = _image_bytes("JPEG")
    with pytest.raises(CreatorToolError) as caught:
        _inspect_image(data, source_url="https://cdn.example.test/thumb.jpg", header_content_type="image/gif")
    _assert_code(caught, "thumbnail_validation_failed")


def test_false_extension_is_rejected():
    data = _image_bytes("JPEG")
    with pytest.raises(CreatorToolError) as caught:
        _inspect_image(data, source_url="https://cdn.example.test/thumb.png", header_content_type="image/jpeg")
    _assert_code(caught, "thumbnail_validation_failed")


def test_extensionless_https_image_is_allowed_when_bytes_are_valid():
    data = _image_bytes("PNG")
    result = _inspect_image(data, source_url="https://cdn.example.test/render?id=1", header_content_type="application/octet-stream")
    assert result["thumbnail_valid"] is True
    assert result["extension_consistent"] is True


def test_corrupted_image_is_rejected():
    with pytest.raises(CreatorToolError) as caught:
        _inspect_image(b"not-an-image", source_url="https://cdn.example.test/thumb.jpg", header_content_type="image/jpeg")
    _assert_code(caught, "thumbnail_decode_failed")


def test_dimensions_below_minimum_are_rejected():
    data = _image_bytes("JPEG", (320, 180))
    with pytest.raises(CreatorToolError) as caught:
        _inspect_image(data, source_url="https://cdn.example.test/thumb.jpg", header_content_type="image/jpeg")
    exc = _assert_code(caught, "thumbnail_validation_failed")
    assert exc.details["dimensions_valid"] is False


@pytest.mark.parametrize("url", [
    "http://example.com/thumb.jpg",
    "file:///tmp/thumb.jpg",
    "ftp://example.com/thumb.jpg",
    "https://user:pass@example.com/thumb.jpg",
    "https://example.com:8443/thumb.jpg",
])
def test_non_https_or_credentialed_sources_are_rejected(url):
    with pytest.raises(CreatorToolError) as caught:
        _canonical_https_url(url)
    _assert_code(caught, "thumbnail_source_invalid")


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/thumb.jpg",
    "https://10.0.0.1/thumb.jpg",
    "https://169.254.169.254/latest/meta-data",
    "https://[::1]/thumb.jpg",
])
def test_private_and_metadata_ips_are_rejected(url):
    with pytest.raises(CreatorToolError) as caught:
        _validate_public_host(url)
    _assert_code(caught, "thumbnail_source_invalid")


class _Response:
    def __init__(self, *, status=200, headers=None, chunks=None):
        self.status_code = status
        self.headers = dict(headers or {})
        self._chunks = list(chunks or [])
        self.closed = False

    @property
    def is_redirect(self):
        return 300 <= self.status_code < 400 and "Location" in self.headers

    @property
    def is_permanent_redirect(self):
        return self.status_code in {301, 308}

    def iter_content(self, chunk_size=65536):
        yield from self._chunks

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def test_redirect_to_localhost_is_blocked(monkeypatch):
    first = _Response(status=302, headers={"Location": "https://127.0.0.1/thumb.jpg"})
    session = _Session([first])
    monkeypatch.setattr(thumbnail_module.requests, "Session", lambda: session)

    def validate(url):
        host = urlsplit(url).hostname
        if host == "127.0.0.1":
            raise CreatorToolError("thumbnail_validation_failed", "blocked")
    monkeypatch.setattr(thumbnail_module, "_validate_public_host", validate)

    with pytest.raises(CreatorToolError) as caught:
        _download_https_thumbnail("https://cdn.example.test/thumb.jpg")
    _assert_code(caught, "thumbnail_validation_failed")
    assert len(session.calls) == 1


def test_remote_timeout_is_explicit(monkeypatch):
    session = _Session(error=requests.Timeout("timeout"))
    monkeypatch.setattr(thumbnail_module.requests, "Session", lambda: session)
    monkeypatch.setattr(thumbnail_module, "_validate_public_host", lambda _url: None)
    with pytest.raises(CreatorToolError) as caught:
        _download_https_thumbnail("https://cdn.example.test/thumb.jpg")
    _assert_code(caught, "thumbnail_source_unavailable")


def test_streaming_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(thumbnail_module, "THUMBNAIL_MAX_SOURCE_BYTES", 10)
    response = _Response(
        status=200,
        headers={"Content-Type": "image/jpeg"},
        chunks=[b"12345678", b"ABCDEFGH"],
    )
    session = _Session([response])
    monkeypatch.setattr(thumbnail_module.requests, "Session", lambda: session)
    monkeypatch.setattr(thumbnail_module, "_validate_public_host", lambda _url: None)
    with pytest.raises(CreatorToolError) as caught:
        _download_https_thumbnail("https://cdn.example.test/thumb.jpg")
    _assert_code(caught, "thumbnail_too_large")


class _Memory:
    def __init__(self):
        self.protected = False
        self.records = []

    def assert_not_recently_edited(self, video_id):
        if self.protected:
            raise RuntimeError("Proteção de memória ativa: este vídeo já foi editado pela ferramenta recentemente.")

    def recent_edit_state(self, video_id):
        last = self.records[-1] if self.records else None
        return SimpleNamespace(
            protected=bool(last) or self.protected,
            video_id=video_id,
            last_action_at=1 if last else None,
            seconds_remaining=604800 if last else 0,
            protection_hours=168,
            last_action_type=last["action_type"] if last else "",
            last_changed_fields=tuple(last["changed_fields"]) if last else (),
        )

    def record_video_action(self, **kwargs):
        self.records.append(kwargs)
        return len(self.records)


class _Request:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _Videos:
    def __init__(self, owner):
        self.owner = owner

    def list(self, *, part, id):
        assert id == self.owner.video_id
        self.owner.read_calls += 1
        if self.owner.pending is not None and self.owner.mode == "delayed" and self.owner.read_calls >= self.owner.pending_visible_at:
            self.owner.thumbnail_map = self.owner.pending
            self.owner.etag = "etag-2"
            self.owner.pending = None
        return _Request(lambda: {"items": [{
            "id": self.owner.video_id,
            "etag": self.owner.etag,
            "snippet": {
                "channelId": self.owner.owner_channel_id,
                "title": "Video",
                "description": "",
                "tags": [],
                "categoryId": "22",
                "defaultLanguage": "pt-BR",
                "thumbnails": dict(self.owner.thumbnail_map),
            },
            "status": {
                "uploadStatus": self.owner.upload_status,
                "privacyStatus": "public",
            },
        }]})


class _Thumbnails:
    def __init__(self, owner):
        self.owner = owner

    def set(self, *, videoId, media_body):
        assert videoId == self.owner.video_id
        assert media_body.mimetype() in {"image/jpeg", "image/png"}
        self.owner.last_uploaded_mime = media_body.mimetype()
        self.owner.last_uploaded_bytes = media_body.getbytes(0, media_body.size())

        def apply():
            self.owner.set_calls += 1
            if self.owner.mode == "error":
                raise RuntimeError("provider rejected thumbnail")
            new = {
                "default": {"url": "https://i.ytimg.com/vi/video/default.jpg?v=2", "width": 120, "height": 90},
                "high": {"url": "https://i.ytimg.com/vi/video/hqdefault.jpg?v=2", "width": 480, "height": 360},
            }
            if self.owner.mode == "success":
                self.owner.thumbnail_map = new
                self.owner.etag = "etag-2"
            elif self.owner.mode == "delayed":
                self.owner.pending = new
            elif self.owner.mode == "never":
                pass
            return {"items": [new]}
        return _Request(apply)


class _YouTube:
    def __init__(self, *, mode="success", owner_channel_id="channel-1", upload_status="processed"):
        self.video_id = "video-1"
        self.owner_channel_id = owner_channel_id
        self.authorized_channel_id = "channel-1"
        self.upload_status = upload_status
        self.mode = mode
        self.etag = "etag-1"
        self.read_calls = 0
        self.set_calls = 0
        self.last_uploaded_bytes = None
        self.last_uploaded_mime = None
        self.pending = None
        self.pending_visible_at = 4
        self.thumbnail_map = {
            "default": {"url": "https://i.ytimg.com/vi/video/default.jpg?v=1", "width": 120, "height": 90},
            "high": {"url": "https://i.ytimg.com/vi/video/hqdefault.jpg?v=1", "width": 480, "height": 360},
        }
        self._videos = _Videos(self)
        self._thumbnails = _Thumbnails(self)

    def videos(self):
        return self._videos

    def thumbnails(self):
        return self._thumbnails


class _Service(ThumbnailUpdateMixin):
    def __init__(self, youtube):
        self.youtube = youtube
        self.context = SimpleNamespace(tenant_id="tenant-1", validate_youtube=lambda: None, data_dir=Path(tempfile.mkdtemp(prefix="yca-thumb-test-")))
        self.memory = _Memory()

    def _youtube(self):
        return self.youtube

    def _owned_video_item(self, video_id, *, part="snippet"):
        if video_id != self.youtube.video_id:
            raise CreatorToolError("video_not_found", "missing")
        item = self.youtube.videos().list(part=part, id=video_id).execute()["items"][0]
        if item["snippet"]["channelId"] != self.youtube.authorized_channel_id:
            raise CreatorToolError("video_not_owned", "foreign")
        return item

    def video_memory_state(self, video_id):
        state = self.memory.recent_edit_state(video_id)
        return {
            "protected": state.protected,
            "video_id": state.video_id,
            "last_action_at": state.last_action_at,
            "seconds_remaining": state.seconds_remaining,
            "protection_hours": state.protection_hours,
            "last_action_type": state.last_action_type,
            "last_changed_fields": list(state.last_changed_fields),
        }


def _install_fetch(monkeypatch, data_ref):
    def fake_fetch(url):
        data = data_ref["data"]
        return data, _validation(data, url=url)
    monkeypatch.setattr(thumbnail_module, "_download_https_thumbnail", fake_fetch)


def _preview(service):
    return service.preview_video_thumbnail_update(
        video_id="video-1",
        thumbnail_url="https://cdn.example.test/thumb.jpg",
    )


def test_thumbnail_preview_is_read_only_and_signed(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    data_ref = {"data": _image_bytes("JPEG")}
    _install_fetch(monkeypatch, data_ref)
    youtube = _YouTube()
    service = _Service(youtube)

    preview = _preview(service)

    assert youtube.set_calls == 0
    assert preview["validation"]["thumbnail_valid"] is True
    assert preview["proposed"]["image_sha256"]
    assert preview["approval_payload"]["baseline_digest"]
    assert preview["requires_explicit_user_confirmation"] is True
    assert preview["rollback_supported"] is False


def test_url_is_not_downloaded_again_after_preview(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setattr(thumbnail_module.time, "sleep", lambda _delay: None)
    data_ref = {"data": _image_bytes("JPEG"), "calls": 0}

    def fake_fetch(url):
        data_ref["calls"] += 1
        data = data_ref["data"]
        return data, _validation(data, url=url)

    monkeypatch.setattr(thumbnail_module, "_download_https_thumbnail", fake_fetch)
    youtube = _YouTube()
    service = _Service(youtube)
    preview = _preview(service)
    assert data_ref["calls"] == 1

    staging = ThumbnailStagingStore(service.context.data_dir)
    staged_bytes, _ = staging.load(
        staging_id=preview["staging_id"],
        video_id="video-1",
        expected_sha256=preview["normalized"]["sha256"],
    )

    # Simulate a mutable URL changing after preview. Apply must use staged bytes.
    data_ref["data"] = _image_bytes("JPEG", (1920, 1080))
    result = service.apply_video_thumbnail_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )
    assert result["persisted_verified"] is True
    assert data_ref["calls"] == 1
    assert youtube.set_calls == 1
    assert youtube.last_uploaded_bytes == staged_bytes
    assert youtube.last_uploaded_mime == preview["normalized"]["mime_type"]


def test_tampered_staged_bytes_are_blocked_before_write(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    data_ref = {"data": _image_bytes("JPEG")}
    _install_fetch(monkeypatch, data_ref)
    youtube = _YouTube()
    service = _Service(youtube)
    preview = _preview(service)

    store = ThumbnailStagingStore(service.context.data_dir)
    blob, _meta = store._paths(preview["staging_id"])
    blob.write_bytes(_image_bytes("JPEG", (1920, 1080)))

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_thumbnail_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )
    _assert_code(caught, "thumbnail_hash_mismatch")
    assert youtube.set_calls == 0


def test_video_id_change_after_preview_is_blocked(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    data_ref = {"data": _image_bytes("JPEG")}
    _install_fetch(monkeypatch, data_ref)
    service = _Service(_YouTube())
    preview = _preview(service)
    preview["approval_payload"]["proposed"]["video_id"] = "other-video"

    with pytest.raises(ValueError):
        service.apply_video_thumbnail_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )


def test_expired_thumbnail_token_is_rejected(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    data_ref = {"data": _image_bytes("JPEG")}
    _install_fetch(monkeypatch, data_ref)
    service = _Service(_YouTube())
    preview = _preview(service)
    token = ApprovalTokenSigner(SECRET).issue(
        "update_video_thumbnail",
        "video-1",
        preview["approval_payload"],
        now=1,
    )
    with pytest.raises(ValueError, match="expired"):
        service.apply_video_thumbnail_update(
            approval_payload=preview["approval_payload"],
            approval_token=token,
        )


def test_foreign_video_is_rejected_before_download(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    called = {"fetch": 0}
    monkeypatch.setattr(thumbnail_module, "_download_https_thumbnail", lambda _url: called.__setitem__("fetch", 1))
    service = _Service(_YouTube(owner_channel_id="foreign-channel"))
    with pytest.raises(CreatorToolError) as caught:
        _preview(service)
    _assert_code(caught, "video_not_owned")
    assert called["fetch"] == 0


def test_recent_edit_protection_blocks_preview_before_download(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    called = {"fetch": 0}
    monkeypatch.setattr(thumbnail_module, "_download_https_thumbnail", lambda _url: called.__setitem__("fetch", 1))
    service = _Service(_YouTube())
    service.memory.protected = True
    with pytest.raises(RuntimeError, match="Proteção"):
        _preview(service)
    assert called["fetch"] == 0


def test_unprocessed_video_is_not_editable(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    data_ref = {"data": _image_bytes("JPEG")}
    _install_fetch(monkeypatch, data_ref)
    service = _Service(_YouTube(upload_status="uploaded"))
    with pytest.raises(CreatorToolError) as caught:
        _preview(service)
    _assert_code(caught, "thumbnail_write_failed")


def test_baseline_change_blocks_write(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    data_ref = {"data": _image_bytes("JPEG")}
    _install_fetch(monkeypatch, data_ref)
    youtube = _YouTube()
    service = _Service(youtube)
    preview = _preview(service)
    youtube.etag = "etag-external"

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_thumbnail_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )
    _assert_code(caught, "baseline_changed")
    assert youtube.set_calls == 0


def test_thumbnails_set_success_is_verified_and_protected(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setattr(thumbnail_module.time, "sleep", lambda _delay: None)
    data_ref = {"data": _image_bytes("JPEG")}
    _install_fetch(monkeypatch, data_ref)
    youtube = _YouTube(mode="success")
    service = _Service(youtube)
    preview = _preview(service)

    result = service.apply_video_thumbnail_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    assert result["state"] == "success_verified"
    assert result["persisted_verified"] is True
    assert result["rollback_supported"] is False
    assert youtube.set_calls == 1
    assert result["verification_attempts"] == 1
    assert service.memory.records[-1]["action_type"] == "thumbnail_update"
    assert service.memory.records[-1]["changed_fields"] == ["thumbnail"]
    assert result["recent_edit_protection"]["protected"] is True
    assert result["recent_edit_protection"]["last_action_type"] == "thumbnail_update"


def test_thumbnails_set_error_never_retries(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    data_ref = {"data": _image_bytes("JPEG")}
    _install_fetch(monkeypatch, data_ref)
    youtube = _YouTube(mode="error")
    service = _Service(youtube)
    preview = _preview(service)

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_thumbnail_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )
    _assert_code(caught, "thumbnail_write_failed")
    assert youtube.set_calls == 1


def test_delayed_readback_converges_without_second_write(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setattr(thumbnail_module.time, "sleep", lambda _delay: None)
    data_ref = {"data": _image_bytes("JPEG")}
    _install_fetch(monkeypatch, data_ref)
    youtube = _YouTube(mode="delayed")
    youtube.pending_visible_at = 5
    service = _Service(youtube)
    preview = _preview(service)

    result = service.apply_video_thumbnail_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    assert result["persisted_verified"] is True
    assert result["verification_attempts"] >= 2
    assert youtube.set_calls == 1


def test_readback_never_confirms_without_retry(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setattr(thumbnail_module.time, "sleep", lambda _delay: None)
    data_ref = {"data": _image_bytes("JPEG")}
    _install_fetch(monkeypatch, data_ref)
    youtube = _YouTube(mode="never")
    service = _Service(youtube)
    preview = _preview(service)

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_thumbnail_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )
    exc = _assert_code(caught, "thumbnail_verification_failed")
    assert youtube.set_calls == 1
    assert exc.details["verification_attempts"] == len(THUMBNAIL_VERIFY_DELAYS)
    assert service.memory.records[-1]["action_type"] == "thumbnail_update_uncertain"


def _mcp_setup(monkeypatch, tmp_path, service):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setenv("YCA_AUTH_ISSUER_URL", "https://auth.example.test")
    monkeypatch.setenv("YCA_CHATGPT_OAUTH_ISSUER_URL", "https://creator.example.test")
    monkeypatch.setenv("YCA_MCP_PUBLIC_URL", "https://mcp.example.test/mcp")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example.test/introspect")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_ID", "client")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_SECRET", "secret")
    store = PublicationStore(tmp_path / "operations.sqlite3")
    monkeypatch.setattr(base_mcp, "_require_scope", lambda _scope: None)
    monkeypatch.setattr(base_mcp, "_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(base_mcp, "_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(base_mcp, "_tenant_id", lambda: "tenant-1")
    monkeypatch.setattr(base_mcp, "_ops_store", lambda: store)
    monkeypatch.setattr(management, "_service", lambda: service)


def _mcp_payload(result):
    assert result.content
    return json.loads(result.content[0].text)


def test_mcp_requires_explicit_confirmation_and_blocks_replay(monkeypatch, tmp_path):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setattr(thumbnail_module.time, "sleep", lambda _delay: None)
    data_ref = {"data": _image_bytes("JPEG")}
    _install_fetch(monkeypatch, data_ref)
    youtube = _YouTube(mode="success")
    service = _Service(youtube)
    _mcp_setup(monkeypatch, tmp_path, service)

    async def scenario():
        async with Client(management.create_server(), raise_exceptions=True) as client:
            preview = _mcp_payload(await client.call_tool(
                "preview_video_thumbnail_update",
                {"video_id": "video-1", "thumbnail_url": "https://cdn.example.test/thumb.jpg"},
            ))
            assert preview["success"] is True
            args = {
                "approval_payload": preview["approval_payload"],
                "approval_token": preview["approval_token"],
                "user_confirmed": False,
            }
            blocked = _mcp_payload(await client.call_tool("apply_video_thumbnail_update", args))
            assert blocked["success"] is False
            assert blocked["error"]["code"] == "confirmation_required"
            assert youtube.set_calls == 0

            args["user_confirmed"] = True
            applied = _mcp_payload(await client.call_tool("apply_video_thumbnail_update", args))
            assert applied["success"] is True
            assert applied["persisted_verified"] is True
            assert youtube.set_calls == 1

            replay = _mcp_payload(await client.call_tool("apply_video_thumbnail_update", args))
            assert replay["success"] is False
            assert replay["error"]["code"] == "approval_replayed"
            assert youtube.set_calls == 1

    asyncio.run(scenario())


def test_chatgpt_file_apply_uses_staged_bytes_without_reresolving(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setattr(thumbnail_module.time, "sleep", lambda _delay: None)
    original = _image_bytes("PNG", (1672, 941))
    changed = _image_bytes("PNG", (1280, 720))
    calls = {"count": 0}

    def fake_download(url, *, source_kind):
        calls["count"] += 1
        data = original if calls["count"] == 1 else changed
        return data, {
            "headers": {"Content-Type": "image/png"},
            "source_url_sha256": "signed-url-hash",
            "redirect_count": 0,
            "final_url": url,
        }

    monkeypatch.setattr(thumbnail_module, "_download_https_bytes", fake_download)
    youtube = _YouTube(mode="success")
    service = _Service(youtube)
    preview = service.preview_video_thumbnail_update(
        video_id="video-1",
        thumbnail_file={
            "download_url": "https://files.example.test/private/signed",
            "file_id": "file_test_generated_thumbnail",
            "mime_type": "image/png",
            "file_name": "generated.png",
        },
    )

    assert preview["source"]["source_type"] == "chatgpt_file"
    assert calls["count"] == 1
    approved_sha = preview["normalized"]["sha256"]

    result = service.apply_video_thumbnail_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    assert result["persisted_verified"] is True
    assert result["thumbnail"]["normalized_sha256"] == approved_sha
    assert calls["count"] == 1
    assert youtube.set_calls == 1
