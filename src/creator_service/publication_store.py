from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_after_seconds: int


class PublicationStore:
    """Small production-support store sharing the tenant SQLite database file.

    It contains only operational counters and sanitized audit metadata. Secrets,
    OAuth tokens and raw prompts must never be written here.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS rate_limit_windows (
                    key_hash TEXT NOT NULL,
                    bucket INTEGER NOT NULL,
                    hits INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY(key_hash, bucket)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at INTEGER NOT NULL,
                    tenant_id TEXT,
                    event_type TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    request_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_time
                    ON audit_events(tenant_id, created_at DESC);
                """
            )

    @staticmethod
    def _hash_key(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def consume_rate_limit(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        now: int | None = None,
    ) -> RateLimitDecision:
        now = int(time.time() if now is None else now)
        limit = max(1, int(limit))
        window_seconds = max(1, int(window_seconds))
        bucket = now // window_seconds
        reset_after = window_seconds - (now % window_seconds)
        key_hash = self._hash_key(key)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO rate_limit_windows(key_hash,bucket,hits,updated_at) VALUES(?,?,1,?) "
                "ON CONFLICT(key_hash,bucket) DO UPDATE SET hits=hits+1, updated_at=excluded.updated_at",
                (key_hash, bucket, now),
            )
            row = conn.execute(
                "SELECT hits FROM rate_limit_windows WHERE key_hash=? AND bucket=?",
                (key_hash, bucket),
            ).fetchone()
            hits = int(row[0]) if row else limit + 1
            conn.execute(
                "DELETE FROM rate_limit_windows WHERE bucket < ?",
                (bucket - 2,),
            )
        return RateLimitDecision(
            allowed=hits <= limit,
            limit=limit,
            remaining=max(0, limit - hits),
            reset_after_seconds=reset_after,
        )

    def record_event(
        self,
        *,
        event_type: str,
        outcome: str,
        tenant_id: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        safe_metadata = self._sanitize_metadata(metadata or {})
        payload = json.dumps(safe_metadata, ensure_ascii=False, separators=(",", ":"))[:4000]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_events(created_at,tenant_id,event_type,outcome,request_id,metadata_json) "
                "VALUES(?,?,?,?,?,?)",
                (
                    int(time.time()),
                    tenant_id,
                    str(event_type)[:80],
                    str(outcome)[:40],
                    str(request_id or "")[:80] or None,
                    payload,
                ),
            )

    @classmethod
    def _sanitize_metadata(cls, value: Any) -> Any:
        forbidden = ("token", "secret", "password", "api_key", "authorization", "cookie")
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                key_text = str(key)
                if any(word in key_text.casefold() for word in forbidden):
                    clean[key_text] = "[redacted]"
                else:
                    clean[key_text] = cls._sanitize_metadata(item)
            return clean
        if isinstance(value, (list, tuple)):
            return [cls._sanitize_metadata(item) for item in value[:50]]
        if isinstance(value, str):
            return value[:500]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)[:500]
