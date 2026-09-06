import json
from pathlib import Path

import pytest

from creator_service.upload_safety import (
    UploadCapacityError,
    UploadSafetyPolicy,
    active_usage,
    ensure_capacity,
    ensure_chunk_headroom,
    purge_expired_sessions,
)


def _session(root: Path, name: str, *, expires_at: int, video_size: int, thumb_size: int = 0) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "expires_at": expires_at,
                "video": {"size": video_size},
                "thumbnail": {"size": thumb_size},
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_purge_expired_sessions_only_removes_expired(tmp_path):
    root = tmp_path / "uploads"
    old = _session(root, "old", expires_at=100, video_size=10)
    live = _session(root, "live", expires_at=1000, video_size=20)
    removed = purge_expired_sessions(root, policy=UploadSafetyPolicy(ttl_seconds=60), now=500)
    assert removed == 1
    assert not old.exists()
    assert live.exists()


def test_active_usage_counts_declared_bytes(tmp_path):
    root = tmp_path / "uploads"
    _session(root, "a", expires_at=1000, video_size=100, thumb_size=5)
    _session(root, "b", expires_at=1000, video_size=200, thumb_size=7)
    assert active_usage(root, now=500) == (2, 312)


def test_capacity_rejects_too_many_active_sessions(tmp_path):
    root = tmp_path / "uploads"
    _session(root, "a", expires_at=1000, video_size=10)
    policy = UploadSafetyPolicy(max_active_sessions=1, max_staged_bytes=1000, min_free_bytes=100)
    with pytest.raises(UploadCapacityError):
        ensure_capacity(root, 10, policy=policy, disk_free_bytes=1000)


def test_capacity_rejects_tenant_staging_quota(tmp_path):
    root = tmp_path / "uploads"
    _session(root, "a", expires_at=1000, video_size=700)
    policy = UploadSafetyPolicy(max_active_sessions=2, max_staged_bytes=1000, min_free_bytes=100)
    with pytest.raises(UploadCapacityError):
        ensure_capacity(root, 400, policy=policy, disk_free_bytes=5000)


def test_capacity_preserves_disk_reserve_before_writing(tmp_path):
    root = tmp_path / "uploads"
    policy = UploadSafetyPolicy(max_active_sessions=2, max_staged_bytes=5000, min_free_bytes=1000)
    with pytest.raises(UploadCapacityError):
        ensure_capacity(root, 500, policy=policy, disk_free_bytes=1400)


def test_chunk_headroom_fails_closed(tmp_path):
    root = tmp_path / "uploads"
    policy = UploadSafetyPolicy(min_free_bytes=1000)
    ensure_chunk_headroom(root, 100, policy=policy, disk_free_bytes=1200)
    with pytest.raises(UploadCapacityError):
        ensure_chunk_headroom(root, 250, policy=policy, disk_free_bytes=1200)
