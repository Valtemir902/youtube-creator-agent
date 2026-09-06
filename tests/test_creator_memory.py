from __future__ import annotations

import pytest

from intelligence.creator_memory import CreatorMemoryStore


def test_recent_edit_is_protected_and_persists(tmp_path):
    path = tmp_path / "creator_memory.sqlite3"
    store = CreatorMemoryStore(path)
    store.record_video_action(
        video_id="abc123",
        action_type="metadata_update",
        surface="test",
        changed_fields=["title"],
        before={"title": "A"},
        after={"title": "B"},
        now=1_000,
    )

    reopened = CreatorMemoryStore(path)
    state = reopened.recent_edit_state("abc123", protection_hours=2, now=1_100)
    assert state.protected is True
    assert state.last_action_type == "metadata_update"
    assert state.last_changed_fields == ("title",)

    with pytest.raises(RuntimeError, match="Proteção de memória ativa"):
        reopened.assert_not_recently_edited("abc123", protection_hours=2, now=1_100)


def test_recent_edit_expires(tmp_path):
    store = CreatorMemoryStore(tmp_path / "creator_memory.sqlite3")
    store.record_video_action(
        video_id="abc123",
        action_type="metadata_update",
        surface="test",
        changed_fields=["title"],
        before={"title": "A"},
        after={"title": "B"},
        now=1_000,
    )
    assert store.recent_edit_state("abc123", protection_hours=1, now=5_000).protected is False


def test_same_second_actions_use_latest_insert_as_recent_state(tmp_path):
    store = CreatorMemoryStore(tmp_path / "creator_memory.sqlite3")
    first_id = store.record_video_action(
        video_id="abc123",
        action_type="metadata_update",
        surface="test",
        changed_fields=["title"],
        before={"title": "A"},
        after={"title": "B"},
        now=1_000,
    )
    second_id = store.record_video_action(
        video_id="abc123",
        action_type="metadata_rollback",
        surface="test",
        changed_fields=["title"],
        before={"title": "B"},
        after={"title": "A"},
        now=1_000,
    )

    assert second_id > first_id
    state = store.recent_edit_state("abc123", protection_hours=2, now=1_100)
    assert state.last_action_type == "metadata_rollback"
    actions = store.recent_actions("abc123", limit=2)
    assert [item["action_type"] for item in actions] == ["metadata_rollback", "metadata_update"]


def test_analysis_cache_roundtrip_and_expiry(tmp_path):
    store = CreatorMemoryStore(tmp_path / "creator_memory.sqlite3")
    store.cache_put("keyword", "vida-na-roca", {"score": 77}, ttl_seconds=60, now=100)
    assert store.cache_get("keyword", "vida-na-roca", now=120) == {"score": 77}
    assert store.cache_get("keyword", "vida-na-roca", now=200) is None
