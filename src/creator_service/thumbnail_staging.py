from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

from .mcp_errors import tool_error


_STAGE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{24,96}$")
_ASSET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
THUMBNAIL_STAGING_TTL_SECONDS = 900


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    temp = path.with_name(path.name + ".tmp-" + secrets.token_hex(6))
    with temp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, path)


class ThumbnailStagingStore:
    """Private, per-tenant staging for exact normalized thumbnail bytes."""

    def __init__(self, data_dir: str | Path, *, ttl_seconds: int = THUMBNAIL_STAGING_TTL_SECONDS):
        self.root = (Path(data_dir).resolve() / "thumbnail_staging").resolve()
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def _paths(self, staging_id: str) -> tuple[Path, Path]:
        value = str(staging_id or "").strip()
        if not _STAGE_ID_RE.fullmatch(value):
            raise tool_error("thumbnail_staging_failed", "Identificador de staging inválido.")
        blob = (self.root / f"{value}.bin").resolve()
        meta = (self.root / f"{value}.json").resolve()
        if blob.parent != self.root or meta.parent != self.root:
            raise tool_error("thumbnail_staging_failed", "Staging fora do diretório autorizado.")
        return blob, meta

    def cleanup_expired(self, *, now: int | None = None) -> int:
        now = int(time.time() if now is None else now)
        removed = 0
        for meta_path in self.root.glob("*.json"):
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                expired = int(metadata.get("expires_at", 0) or 0) <= now
                consumed = bool(metadata.get("consumed", False))
                consumed_at = int(metadata.get("consumed_at", 0) or 0)
                stale_consumed = consumed and consumed_at and consumed_at + 60 <= now
                if not expired and not stale_consumed:
                    continue
                staging_id = meta_path.stem
                blob, meta = self._paths(staging_id)
                blob.unlink(missing_ok=True)
                meta.unlink(missing_ok=True)
                removed += 1
            except Exception:
                # Cleanup must never make a valid preview fail. Unknown files remain untouched.
                continue
        return removed

    def create(
        self,
        *,
        video_id: str,
        data: bytes,
        sha256: str,
        mime_type: str,
        width: int,
        height: int,
        source_type: str,
        source_sha256: str,
        now: int | None = None,
    ) -> dict[str, Any]:
        self.cleanup_expired(now=now)
        actual_sha = _sha256_bytes(data)
        if actual_sha != str(sha256):
            raise tool_error("thumbnail_hash_mismatch", "O hash dos bytes normalizados mudou antes do staging.")
        created_at = int(time.time() if now is None else now)
        staging_id = secrets.token_urlsafe(32)
        blob, meta = self._paths(staging_id)
        metadata = {
            "staging_id": staging_id,
            "video_id": str(video_id),
            "sha256": actual_sha,
            "mime_type": str(mime_type),
            "width": int(width),
            "height": int(height),
            "file_size_bytes": len(data),
            "source_type": str(source_type),
            "source_sha256": str(source_sha256),
            "created_at": created_at,
            "expires_at": created_at + self.ttl_seconds,
            "consumed": False,
            "consumed_at": None,
        }
        try:
            _atomic_write(blob, data)
            _atomic_write(meta, json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except Exception as exc:
            blob.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
            raise tool_error("thumbnail_staging_failed", "Não foi possível preservar a thumbnail aprovada em staging privado.") from exc
        return metadata

    def load(
        self,
        *,
        staging_id: str,
        video_id: str,
        expected_sha256: str,
        now: int | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        self.cleanup_expired(now=now)
        blob, meta = self._paths(staging_id)
        if not meta.exists():
            raise tool_error("thumbnail_staging_expired", "O staging da thumbnail não existe mais ou expirou.")
        try:
            metadata = json.loads(meta.read_text(encoding="utf-8"))
        except Exception as exc:
            raise tool_error("thumbnail_staging_failed", "Os metadados do staging da thumbnail estão inválidos.") from exc
        current = int(time.time() if now is None else now)
        if bool(metadata.get("consumed", False)):
            raise tool_error("thumbnail_staging_failed", "O staging da thumbnail já foi consumido.")
        if int(metadata.get("expires_at", 0) or 0) <= current:
            blob.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
            raise tool_error("thumbnail_staging_expired", "O staging da thumbnail expirou.")
        if not blob.exists():
            raise tool_error("thumbnail_staging_failed", "Os bytes staged da thumbnail não estão disponíveis.")
        if str(metadata.get("video_id", "")) != str(video_id):
            raise tool_error("approval_invalid", "O staging aprovado pertence a outro vídeo.")
        if str(metadata.get("sha256", "")) != str(expected_sha256):
            raise tool_error("thumbnail_hash_mismatch", "O hash aprovado não corresponde ao staging.")
        try:
            data = blob.read_bytes()
        except OSError as exc:
            raise tool_error("thumbnail_staging_failed", "Não foi possível ler os bytes staged da thumbnail.") from exc
        actual_sha = _sha256_bytes(data)
        if actual_sha != str(expected_sha256) or len(data) != int(metadata.get("file_size_bytes", -1)):
            raise tool_error("thumbnail_hash_mismatch", "Os bytes staged da thumbnail não correspondem ao hash aprovado.")
        return data, metadata

    def mark_consumed(self, staging_id: str, *, now: int | None = None) -> dict[str, Any]:
        blob, meta = self._paths(staging_id)
        if not meta.exists():
            raise tool_error("thumbnail_staging_expired", "O staging da thumbnail não existe mais.")
        try:
            metadata = json.loads(meta.read_text(encoding="utf-8"))
        except Exception as exc:
            raise tool_error("thumbnail_staging_failed", "Os metadados do staging da thumbnail estão inválidos.") from exc
        if bool(metadata.get("consumed", False)):
            raise tool_error("thumbnail_staging_failed", "O staging da thumbnail já foi consumido.")
        metadata["consumed"] = True
        metadata["consumed_at"] = int(time.time() if now is None else now)
        _atomic_write(meta, json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        # Keep the blob only briefly; apply already holds the exact bytes in memory.
        blob.unlink(missing_ok=True)
        return metadata


class ThumbnailAssetStore:
    """Read-only resolver for assets explicitly provisioned inside the tenant sandbox.

    There is intentionally no arbitrary-path API. An authorized integration may place
    <asset_id>.bin + <asset_id>.json under data_dir/thumbnail_assets.
    """

    def __init__(self, data_dir: str | Path):
        self.root = (Path(data_dir).resolve() / "thumbnail_assets").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def resolve(self, asset_id: str) -> tuple[bytes, dict[str, Any]]:
        value = str(asset_id or "").strip()
        if not _ASSET_ID_RE.fullmatch(value):
            raise tool_error("thumbnail_source_invalid", "Identificador de asset inválido.")
        blob = (self.root / f"{value}.bin").resolve()
        meta = (self.root / f"{value}.json").resolve()
        if blob.parent != self.root or meta.parent != self.root:
            raise tool_error("thumbnail_source_invalid", "Asset fora do sandbox autorizado.")
        if not blob.exists() or not meta.exists():
            raise tool_error(
                "thumbnail_source_unavailable",
                "O asset não está disponível no sandbox privado deste tenant.",
            )
        try:
            metadata = json.loads(meta.read_text(encoding="utf-8"))
            data = blob.read_bytes()
        except Exception as exc:
            raise tool_error("thumbnail_source_unavailable", "Não foi possível resolver o asset interno.") from exc
        expected = str(metadata.get("sha256", "") or "")
        actual = _sha256_bytes(data)
        if expected and expected != actual:
            raise tool_error("thumbnail_hash_mismatch", "O asset interno não corresponde ao hash registrado.")
        return data, {
            "asset_id": value,
            "source_type": str(metadata.get("source_type", "internal_asset") or "internal_asset"),
            "source_name": str(metadata.get("source_name", value) or value),
            "sha256": actual,
        }
