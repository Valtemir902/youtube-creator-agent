from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_RECENT_EDIT_PROTECTION_HOURS = 168  # 7 days


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def payload_digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def protection_hours_from_env() -> int:
    raw = os.environ.get("YCA_RECENT_EDIT_PROTECTION_HOURS", "").strip()
    if not raw:
        return DEFAULT_RECENT_EDIT_PROTECTION_HOURS
    try:
        return max(1, min(24 * 365, int(raw)))
    except ValueError:
        return DEFAULT_RECENT_EDIT_PROTECTION_HOURS


@dataclass(frozen=True)
class RecentEditState:
    protected: bool
    video_id: str
    last_action_at: int | None
    seconds_remaining: int
    protection_hours: int
    last_action_type: str = ""
    last_changed_fields: tuple[str, ...] = ()


class CreatorMemoryStore:
    """Durable local memory for actions and reusable analysis cache.

    The database intentionally stores derived metadata and hashes, not OAuth/API
    secrets. WAL mode and indexes keep it usable as the history grows.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS video_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    surface TEXT NOT NULL,
                    changed_fields_json TEXT NOT NULL,
                    before_digest TEXT NOT NULL,
                    after_digest TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_video_actions_video_time
                    ON video_actions(video_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_video_actions_time
                    ON video_actions(created_at DESC);

                CREATE TABLE IF NOT EXISTS analysis_cache (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    PRIMARY KEY(namespace, cache_key)
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_cache_expiry
                    ON analysis_cache(expires_at);
                """
            )

    def record_video_action(
        self,
        *,
        video_id: str,
        action_type: str,
        surface: str,
        changed_fields: list[str] | tuple[str, ...],
        before: Any,
        after: Any,
        details: dict[str, Any] | None = None,
        now: int | None = None,
    ) -> int:
        video_id = (video_id or "").strip()
        if not video_id:
            raise ValueError("video_id é obrigatório para registrar uma ação.")
        timestamp = int(time.time() if now is None else now)
        safe_details = dict(details or {})
        # Never turn this database into a credential graveyard.
        for key in list(safe_details):
            if any(token in key.lower() for token in ("token", "secret", "password", "api_key", "cookie", "authorization")):
                safe_details[key] = "[redacted]"
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO video_actions(video_id,action_type,surface,changed_fields_json,before_digest,after_digest,details_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    video_id,
                    (action_type or "metadata_update")[:80],
                    (surface or "unknown")[:80],
                    _canonical(list(changed_fields)),
                    payload_digest(before),
                    payload_digest(after),
                    _canonical(safe_details),
                    timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def recent_edit_state(
        self,
        video_id: str,
        *,
        protection_hours: int | None = None,
        now: int | None = None,
    ) -> RecentEditState:
        video_id = (video_id or "").strip()
        hours = int(protection_hours or protection_hours_from_env())
        timestamp = int(time.time() if now is None else now)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT action_type, changed_fields_json, created_at FROM video_actions "
                "WHERE video_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
                (video_id,),
            ).fetchone()
        if row is None:
            return RecentEditState(False, video_id, None, 0, hours)
        created_at = int(row["created_at"])
        window = hours * 3600
        remaining = max(0, created_at + window - timestamp)
        try:
            fields = tuple(str(item) for item in json.loads(row["changed_fields_json"]))
        except Exception:
            fields = ()
        return RecentEditState(
            protected=remaining > 0,
            video_id=video_id,
            last_action_at=created_at,
            seconds_remaining=remaining,
            protection_hours=hours,
            last_action_type=str(row["action_type"]),
            last_changed_fields=fields,
        )

    def assert_not_recently_edited(
        self,
        video_id: str,
        *,
        protection_hours: int | None = None,
        now: int | None = None,
    ) -> None:
        state = self.recent_edit_state(video_id, protection_hours=protection_hours, now=now)
        if not state.protected:
            return
        hours_left = max(1, (state.seconds_remaining + 3599) // 3600)
        raise RuntimeError(
            f"Proteção de memória ativa: este vídeo já foi editado pela ferramenta recentemente. "
            f"Nova edição bloqueada por aproximadamente {hours_left}h."
        )

    def recent_actions(self, video_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,video_id,action_type,surface,changed_fields_json,before_digest,after_digest,details_json,created_at "
                "FROM video_actions WHERE video_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
                ((video_id or "").strip(), max(1, min(200, int(limit)))),
            ).fetchall()
        output = []
        for row in rows:
            output.append(
                {
                    "id": int(row["id"]),
                    "video_id": str(row["video_id"]),
                    "action_type": str(row["action_type"]),
                    "surface": str(row["surface"]),
                    "changed_fields": json.loads(row["changed_fields_json"]),
                    "before_digest": str(row["before_digest"]),
                    "after_digest": str(row["after_digest"]),
                    "details": json.loads(row["details_json"]),
                    "created_at": int(row["created_at"]),
                }
            )
        return output

    def cache_put(
        self,
        namespace: str,
        cache_key: str,
        payload: Any,
        *,
        ttl_seconds: int | None = None,
        now: int | None = None,
    ) -> None:
        timestamp = int(time.time() if now is None else now)
        expires_at = timestamp + int(ttl_seconds) if ttl_seconds else None
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO analysis_cache(namespace,cache_key,payload_json,created_at,expires_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(namespace,cache_key) DO UPDATE SET payload_json=excluded.payload_json,created_at=excluded.created_at,expires_at=excluded.expires_at",
                (
                    (namespace or "default")[:100],
                    (cache_key or "")[:500],
                    _canonical(payload),
                    timestamp,
                    expires_at,
                ),
            )

    def cache_get(
        self,
        namespace: str,
        cache_key: str,
        *,
        now: int | None = None,
    ) -> Any | None:
        timestamp = int(time.time() if now is None else now)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json,expires_at FROM analysis_cache WHERE namespace=? AND cache_key=?",
                ((namespace or "default")[:100], (cache_key or "")[:500]),
            ).fetchone()
            if row is None:
                return None
            expires_at = row["expires_at"]
            if expires_at is not None and int(expires_at) < timestamp:
                conn.execute(
                    "DELETE FROM analysis_cache WHERE namespace=? AND cache_key=?",
                    ((namespace or "default")[:100], (cache_key or "")[:500]),
                )
                return None
        try:
            return json.loads(row["payload_json"])
        except json.JSONDecodeError:
            return None

    def purge_expired_cache(self, *, now: int | None = None) -> int:
        timestamp = int(time.time() if now is None else now)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM analysis_cache WHERE expires_at IS NOT NULL AND expires_at < ?",
                (timestamp,),
            )
            return int(cursor.rowcount or 0)
