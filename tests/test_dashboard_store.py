from __future__ import annotations

import pytest

from creator_service.dashboard_store import DashboardActionStore


def test_dashboard_action_is_one_time_and_tenant_bound(tmp_path):
    store = DashboardActionStore(tmp_path / "dashboard.sqlite3")
    action_id = store.put(
        tenant_id="tenant-a",
        kind="metadata_update",
        payload={"proposed": {"video_id": "abc123"}},
        secret_token="server-only-token",
        ttl_seconds=900,
        now=1_000,
    )

    with pytest.raises(PermissionError, match="não pertence"):
        store.consume(
            action_id=action_id,
            tenant_id="tenant-b",
            kind="metadata_update",
            now=1_001,
        )

    action = store.consume(
        action_id=action_id,
        tenant_id="tenant-a",
        kind="metadata_update",
        now=1_001,
    )
    assert action.payload["proposed"]["video_id"] == "abc123"
    assert action.secret_token == "server-only-token"

    with pytest.raises(PermissionError, match="já utilizada"):
        store.consume(
            action_id=action_id,
            tenant_id="tenant-a",
            kind="metadata_update",
            now=1_002,
        )


def test_dashboard_action_expiry_blocks_write(tmp_path):
    store = DashboardActionStore(tmp_path / "dashboard.sqlite3")
    action_id = store.put(
        tenant_id="tenant-a",
        kind="metadata_rollback",
        payload={"proposed": {"video_id": "abc123"}},
        secret_token="rollback-token",
        ttl_seconds=60,
        now=1_000,
    )

    with pytest.raises(PermissionError, match="expirada"):
        store.consume(
            action_id=action_id,
            tenant_id="tenant-a",
            kind="metadata_rollback",
            now=1_061,
        )


def test_browser_identifier_does_not_embed_server_token(tmp_path):
    store = DashboardActionStore(tmp_path / "dashboard.sqlite3")
    action_id = store.put(
        tenant_id="tenant-a",
        kind="metadata_update",
        payload={"x": 1},
        secret_token="super-secret-approval-token",
        ttl_seconds=900,
        now=1_000,
    )
    assert "super-secret" not in action_id
    assert len(action_id) >= 24
