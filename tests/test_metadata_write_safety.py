from __future__ import annotations

import pytest

from creator_service.service import CreatorService
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
        return _Request(
            lambda: {
                "items": [
                    {
                        "snippet": dict(self.owner.snippet),
                    }
                ]
            }
        )

    def update(self, *, part: str, body: dict):
        assert part == "snippet"
        assert body["id"] == self.owner.video_id

        def _apply():
            self.owner.update_calls += 1
            self.owner.snippet = dict(body["snippet"])
            return {"id": body["id"], "snippet": dict(self.owner.snippet)}

        return _Request(_apply)


class _FakeYouTube:
    def __init__(self, video_id: str = "abc123"):
        self.video_id = video_id
        self.snippet = {
            "title": "Titulo atual",
            "description": "Descricao atual",
            "tags": ["roca", "maquina"],
            "categoryId": "22",
            "defaultLanguage": "pt-BR",
        }
        self.update_calls = 0
        self._videos = _Videos(self)

    def videos(self):
        return self._videos


class _FakeContext:
    tenant_id = "test-tenant"

    def validate_youtube(self):
        return None


def _service(tmp_path, monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.delenv("YCA_RECENT_EDIT_PROTECTION_HOURS", raising=False)

    service = CreatorService.__new__(CreatorService)
    service.context = _FakeContext()
    service.memory = CreatorMemoryStore(tmp_path / "creator_memory.sqlite3")

    youtube = _FakeYouTube()
    monkeypatch.setattr(service, "_youtube", lambda: youtube)
    return service, youtube


def test_stale_baseline_is_rejected_before_youtube_write(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)

    preview = service.preview_video_metadata_update(
        video_id=youtube.video_id,
        title="Titulo aprovado",
    )

    # Simula uma alteracao externa depois da previa e antes do apply.
    youtube.snippet["title"] = "Alterado fora do agente"

    with pytest.raises(RuntimeError, match="mudou desde a prévia"):
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    assert youtube.update_calls == 0


def test_successful_apply_records_memory_and_blocks_immediate_reedit(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)

    preview = service.preview_video_metadata_update(
        video_id=youtube.video_id,
        title="Titulo aprovado",
    )
    result = service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    assert result["ok"] is True
    assert result["changed_fields"] == ["title"]
    assert youtube.update_calls == 1

    state = service.memory.recent_edit_state(youtube.video_id)
    assert state.protected is True
    assert state.protection_hours == 168
    assert state.last_changed_fields == ("title",)

    # Documenta a protecao atual: uma segunda previa, inclusive para rollback,
    # fica bloqueada durante a janela de recent-edit.
    with pytest.raises(RuntimeError, match="Proteção de memória ativa"):
        service.preview_video_metadata_update(
            video_id=youtube.video_id,
            title="Titulo de rollback",
        )
