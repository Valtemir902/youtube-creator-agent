from __future__ import annotations

from creator_service import cloud_mcp_server_responsible as responsible_mcp
from creator_service.handoff import open_handoff


SECRET = "0123456789abcdef0123456789abcdef"


class _Context:
    tenant_id = "tenant-1"


class _FakeService:
    def __init__(self):
        self.context = _Context()
        self.current = {
            "video_id": "video-1",
            "title": "Original title",
            "description": "Original description",
            "tags": ["old"],
            "categoryId": "10",
            "defaultLanguage": "en",
        }

    def _authorized_channel_id(self):
        return "channel-1"

    def preview_video_metadata_update(self, *, video_id, title=None, description=None, tags=None):
        assert video_id == "video-1"
        proposed = dict(self.current)
        proposed["video_id"] = video_id
        if title is not None:
            proposed["title"] = title
        if description is not None:
            proposed["description"] = description
        if tags is not None:
            proposed["tags"] = tags
        changed = {
            key: self.current.get(key) != proposed.get(key)
            for key in ("title", "description", "tags", "categoryId")
        }
        return {
            "video_id": video_id,
            "current": dict(self.current),
            "proposed": proposed,
            "changed": changed,
            "approval_payload": {"baseline_digest": "opaque", "proposed": proposed},
            "approval_token": "signed-direct-apply-token",
            "requires_explicit_user_confirmation": True,
        }


def test_historical_preview_requires_read_scope_and_returns_one_click_handoff(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setenv("YCA_ONBOARDING_PUBLIC_URL", "https://creator.example.com")
    scopes: list[str] = []
    monkeypatch.setattr(responsible_mcp.base, "_require_scope", lambda scope: scopes.append(scope))
    monkeypatch.setattr(responsible_mcp.base, "_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(responsible_mcp.base, "_tenant_id", lambda: "tenant-1")
    monkeypatch.setattr(responsible_mcp, "_service", lambda: _FakeService())

    result = responsible_mcp._preview_metadata_with_handoff(
        video_id="video-1",
        title="Approved title",
        description=None,
        tags=None,
    )

    assert scopes == [responsible_mcp.base.READ_SCOPE]
    assert result["ok"] is True
    assert result["approval_token"] == "signed-direct-apply-token"
    assert result["handoff_fallback_supported"] is True
    assert result["button_label"] == "Enviar e aplicar mudanças"
    assert result["handoff_url"].startswith("https://creator.example.com/handoff/v1#ticket=v1.")

    ticket = result["handoff_url"].split("#ticket=", 1)[1]
    package = open_handoff(ticket, secret=SECRET)
    assert package.tenant_id == "tenant-1"
    assert package.channel_id == "channel-1"
    assert package.video_id == "video-1"
    assert package.changed_fields == ("title",)
    assert package.proposed["title"] == "Approved title"


def test_historical_preview_with_no_diff_does_not_create_executable_ticket(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setenv("YCA_ONBOARDING_PUBLIC_URL", "https://creator.example.com")
    monkeypatch.setattr(responsible_mcp.base, "_require_scope", lambda _scope: None)
    monkeypatch.setattr(responsible_mcp.base, "_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(responsible_mcp.base, "_tenant_id", lambda: "tenant-1")
    monkeypatch.setattr(responsible_mcp, "_service", lambda: _FakeService())

    result = responsible_mcp._preview_metadata_with_handoff(
        video_id="video-1",
        title="Original title",
        description="Original description",
        tags=["old"],
    )

    assert result["ok"] is True
    assert result["changed_fields"] == []
    assert result["handoff_url"] == ""
    assert result["requires_user_click"] is False