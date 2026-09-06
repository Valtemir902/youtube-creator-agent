from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


class UploadCapacityError(RuntimeError):
    """Raised when an upload would violate bounded ephemeral-storage policy."""


@dataclass(frozen=True)
class UploadSafetyPolicy:
    ttl_seconds: int = 30 * 60
    max_active_sessions: int = 2
    max_staged_bytes: int = 16 * 1024 * 1024 * 1024
    min_free_bytes: int = 5 * 1024 * 1024 * 1024


def _manifest(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def purge_expired_sessions(root: Path, *, policy: UploadSafetyPolicy, now: int | None = None) -> int:
    """Delete only expired/old session directories below a tenant-owned upload root."""
    root = root.resolve()
    if not root.exists():
        return 0
    current = int(time.time() if now is None else now)
    removed = 0
    for child in root.iterdir():
        if not child.is_dir() or child.is_symlink():
            continue
        try:
            resolved = child.resolve()
        except OSError:
            continue
        if root not in resolved.parents:
            continue
        manifest_path = resolved / "manifest.json"
        data = _manifest(manifest_path) if manifest_path.exists() else None
        if data is not None:
            expires_at = int(data.get("expires_at", 0) or 0)
            expired = expires_at > 0 and expires_at <= current
        else:
            try:
                expired = int(resolved.stat().st_mtime) + policy.ttl_seconds <= current
            except OSError:
                expired = False
        if expired:
            shutil.rmtree(resolved, ignore_errors=True)
            removed += 1
    return removed


def active_usage(root: Path, *, now: int | None = None) -> tuple[int, int]:
    """Return active session count and declared staged bytes without following symlinks."""
    root = root.resolve()
    if not root.exists():
        return 0, 0
    current = int(time.time() if now is None else now)
    count = 0
    total = 0
    for child in root.iterdir():
        if not child.is_dir() or child.is_symlink():
            continue
        data = _manifest(child / "manifest.json")
        if data is None:
            continue
        expires_at = int(data.get("expires_at", 0) or 0)
        if expires_at and expires_at <= current:
            continue
        try:
            video_size = max(0, int((data.get("video") or {}).get("size", 0) or 0))
            thumb_size = max(0, int((data.get("thumbnail") or {}).get("size", 0) or 0))
        except (TypeError, ValueError):
            continue
        count += 1
        total += video_size + thumb_size
    return count, total


def ensure_capacity(
    root: Path,
    requested_bytes: int,
    *,
    policy: UploadSafetyPolicy,
    disk_free_bytes: int | None = None,
) -> tuple[int, int]:
    """Fail closed before creating a new temporary upload session."""
    requested = max(0, int(requested_bytes))
    root.mkdir(parents=True, exist_ok=True)
    purge_expired_sessions(root, policy=policy)
    active_count, staged_bytes = active_usage(root)
    if active_count >= policy.max_active_sessions:
        raise UploadCapacityError("Limite de uploads temporários simultâneos atingido. Conclua ou cancele um upload antes de iniciar outro.")
    if staged_bytes + requested > policy.max_staged_bytes:
        raise UploadCapacityError("Este upload excede a cota temporária segura da conta. Use o modo de processamento no dispositivo para arquivos grandes.")
    free = int(shutil.disk_usage(root).free if disk_free_bytes is None else disk_free_bytes)
    if free - requested < policy.min_free_bytes:
        raise UploadCapacityError("O servidor recusou o staging para preservar a reserva de armazenamento. Nenhum arquivo foi gravado.")
    return active_count, staged_bytes


def ensure_chunk_headroom(
    root: Path,
    incoming_bytes: int,
    *,
    policy: UploadSafetyPolicy,
    disk_free_bytes: int | None = None,
) -> None:
    """Re-check free space immediately before persisting each chunk."""
    incoming = max(0, int(incoming_bytes))
    root.mkdir(parents=True, exist_ok=True)
    free = int(shutil.disk_usage(root).free if disk_free_bytes is None else disk_free_bytes)
    if free - incoming < policy.min_free_bytes:
        raise UploadCapacityError("Upload interrompido para preservar a reserva mínima de armazenamento do servidor.")
