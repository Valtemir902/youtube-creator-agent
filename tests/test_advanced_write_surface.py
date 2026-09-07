from __future__ import annotations

import pytest

from creator_service.advanced_service import AdvancedSafeCreatorService
from intelligence.creator_memory import CreatorMemoryStore


SECRET = "0123456789abcdef0123456789abcdef"


class _Request:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _Videos:
    def __init__(self, owner):
        self.owner = owner

    def list(self, *, part: str, id: str):
        assert part == "snippet"
        assert id == self.owner.video_id
        return _Request(lambda: {"items": [{"snippet": dict(self.owner.snippet)}]})

    def update(self, *, part: str, body: dict):
        assert part == "snippet"
        assert body["id"] == self.owner.video_id

        def _apply():
            self.owner.video_update_calls += 1
            self.owner.snippet = dict(body["snippet"])
            return {"id": body["id"], "snippet": dict(self.owner.snippet)}

        return _Request(_apply)


class _VideoCategories:
    def list(self, *, part: str, regionCode: str):
        assert part == "snippet"
        assert regionCode == "BR"
        return _Request(lambda: {"items": [
            {"id": "22", "snippet": {"title": "People & Blogs", "assignable": True}},
            {"id": "26", "snippet": {"title": "Howto & Style", "assignable": True}},
        ]})


class _Captions:
    def __init__(self, owner):
        self.owner = owner

    def list(self, *, part: str, videoId: str):
        assert part == "snippet"
        assert videoId == self.owner.video_id
        return _Request(lambda: {"items": list(self.owner.caption_items)})

    def insert(self, *, part: str, body: dict, media_body):
        assert part == "snippet"
        assert body["snippet"]["videoId"] == self.owner.video_id
        assert body["snippet"]["language"] == "pt-BR"
        assert media_body is not None

        def _apply():
            self.owner.caption_insert_calls += 1
            item = {
                "id": "caption-1",
                "snippet": {
                    "videoId": self.owner.video_id,
                    "language": body["snippet"]["language"],
                    "name": body["snippet"]["name"],
                    "status": "serving",
                    "isDraft": False,
                },
            }
            self.owner.caption_items = [item]
            return item

        return _Request(_apply)

    def delete(self, *, id: str):
        assert id == "caption-1"

        def _apply():
            self.owner.caption_delete_calls += 1
            self.owner.caption_items = []
            return None

        return _Request(_apply)


class _FakeYouTube:
    def __init__(self):
        self.video_id = "abc123"
        self.snippet = {
            "title": "Titulo atual",
            "description": "Descricao atual",
            "tags": ["roca"],
            "categoryId": "22",
            "defaultLanguage": "pt-BR",
        }
        self.video_update_calls = 0
        self.caption_insert_calls = 0
        self.caption_delete_calls = 0
        self.caption_items = []
        self._videos = _Videos(self)
        self._categories = _VideoCategories()
        self._captions = _Captions(self)

    def videos(self):
        return self._videos

    def videoCategories(self):
        return self._categories

    def captions(self):
        return self._captions


class _FakeContext:
    tenant_id = "test-tenant"

    def validate_youtube(self):
        return None


def _service(tmp_path, monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.delenv("YCA_RECENT_EDIT_PROTECTION_HOURS", raising=False)
    service = AdvancedSafeCreatorService.__new__(AdvancedSafeCreatorService)
    service.context = _FakeContext()
    service.memory = CreatorMemoryStore(tmp_path / "creator_memory.sqlite3")
    youtube = _FakeYouTube()
    monkeypatch.setattr(service, "_youtube", lambda: youtube)
    return service, youtube


def test_category_preview_apply_and_signed_rollback(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)
    preview = service.preview_video_metadata_update(
        video_id=youtube.video_id,
        title="Titulo novo",
        description="Descricao nova",
        category_id="26",
    )
    assert preview["changed"]["title"] is True
    assert preview["changed"]["description"] is True
    assert preview["changed"]["categoryId"] is True
    assert preview["proposed"]["categoryId"] == "26"

    applied = service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )
    assert set(applied["changed_fields"]) == {"title", "description", "categoryId"}
    assert youtube.snippet["categoryId"] == "26"
    assert youtube.video_update_calls == 1

    rollback = applied["rollback_preview"]
    restored = service.apply_video_metadata_rollback(
        rollback_payload=rollback["rollback_payload"],
        rollback_token=rollback["rollback_token"],
    )
    assert restored["rolled_back"] is True
    assert youtube.snippet["categoryId"] == "22"
    assert youtube.snippet["title"] == "Titulo atual"
    assert youtube.video_update_calls == 2


def test_categories_are_listed_without_write(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)
    result = service.list_video_categories("BR")
    assert [item["id"] for item in result["categories"]] == ["22", "26"]
    assert youtube.video_update_calls == 0


def test_caption_preview_requires_valid_timing(tmp_path, monkeypatch):
    service, _ = _service(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="intervalo de tempo"):
        service.preview_caption_upload(
            video_id="abc123",
            language="pt-BR",
            content="texto sem timing",
            caption_format="srt",
        )


def test_caption_upload_and_delete_rollback(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)
    content = "1\n00:00:00,000 --> 00:00:02,000\nTeste de legenda\n"
    preview = service.preview_caption_upload(
        video_id=youtube.video_id,
        language="pt-BR",
        content=content,
        name="Português",
        caption_format="srt",
    )
    assert preview["requires_explicit_user_confirmation"] is True
    assert preview["content_bytes"] > 0

    applied = service.apply_caption_upload(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )
    assert applied["ok"] is True
    assert applied["caption_id"] == "caption-1"
    assert youtube.caption_insert_calls == 1

    listing = service.list_video_captions(youtube.video_id)
    assert listing["captions"][0]["language"] == "pt-BR"

    rollback = applied["rollback_preview"]
    deleted = service.apply_caption_delete(
        rollback_payload=rollback["rollback_payload"],
        rollback_token=rollback["rollback_token"],
    )
    assert deleted["deleted"] is True
    assert youtube.caption_delete_calls == 1
    assert service.list_video_captions(youtube.video_id)["captions"] == []


def test_caption_upload_rejects_tampered_payload(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)
    preview = service.preview_caption_upload(
        video_id=youtube.video_id,
        language="pt-BR",
        content="1\n00:00:00,000 --> 00:00:01,000\nOriginal\n",
        caption_format="srt",
    )
    tampered = dict(preview["approval_payload"])
    tampered["content"] = "1\n00:00:00,000 --> 00:00:01,000\nAdulterado\n"
    with pytest.raises(ValueError, match="changed after approval"):
        service.apply_caption_upload(
            approval_payload=tampered,
            approval_token=preview["approval_token"],
        )
    assert youtube.caption_insert_calls == 0
