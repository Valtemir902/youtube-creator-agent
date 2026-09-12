from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HandoffExecution:
    status: str
    tenant_id: str
    video_id: str
    expires_at: int
    result: dict[str, Any] | None
    error: str
    updated_at: int


class HandoffExecutionStore:
    """Persistent idempotency/result ledger for one-click handoffs.

    Only SHA-256 ticket hashes are stored. The encrypted handoff ticket and its
    metadata payload are never persisted here.
    """

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @staticmethod
    def ticket_hash(ticket: str) -> str:
        return hashlib.sha256(str(ticket).encode("utf-8")).hexdigest()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS handoff_executions (
                    ticket_hash TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error_message TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_handoff_exec_expiry ON handoff_executions(expires_at)"
            )

    def get(self, ticket: str, *, tenant_id: str, video_id: str) -> HandoffExecution | None:
        digest = self.ticket_hash(ticket)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT tenant_id,video_id,expires_at,status,result_json,error_message,updated_at "
                "FROM handoff_executions WHERE ticket_hash=?",
                (digest,),
            ).fetchone()
        if row is None:
            return None
        if str(row["tenant_id"]) != tenant_id or str(row["video_id"]) != video_id:
            raise PermissionError("O registro de idempotência não corresponde ao alvo autenticado.")
        result = None
        if row["result_json"]:
            try:
                parsed = json.loads(str(row["result_json"]))
                if isinstance(parsed, dict):
                    result = parsed
            except json.JSONDecodeError:
                result = None
        return HandoffExecution(
            status=str(row["status"]),
            tenant_id=str(row["tenant_id"]),
            video_id=str(row["video_id"]),
            expires_at=int(row["expires_at"]),
            result=result,
            error=str(row["error_message"] or ""),
            updated_at=int(row["updated_at"]),
        )

    def begin(
        self,
        ticket: str,
        *,
        tenant_id: str,
        video_id: str,
        expires_at: int,
        now: int | None = None,
    ) -> tuple[str, HandoffExecution | None]:
        timestamp = int(time.time() if now is None else now)
        digest = self.ticket_hash(ticket)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM handoff_executions WHERE expires_at < ? AND updated_at < ?",
                (timestamp - 3600, timestamp - 3600),
            )
            row = conn.execute(
                "SELECT tenant_id,video_id,expires_at,status,result_json,error_message,updated_at "
                "FROM handoff_executions WHERE ticket_hash=?",
                (digest,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO handoff_executions(ticket_hash,tenant_id,video_id,expires_at,status,result_json,error_message,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,'','',?,?)",
                    (digest, tenant_id, video_id, int(expires_at), "processing", timestamp, timestamp),
                )
                conn.execute("COMMIT")
                return "new", None
            conn.execute("COMMIT")

        existing = self.get(ticket, tenant_id=tenant_id, video_id=video_id)
        assert existing is not None
        return existing.status, existing

    def mark_success(self, ticket: str, result: dict[str, Any], *, now: int | None = None) -> None:
        timestamp = int(time.time() if now is None else now)
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._connect() as conn:
            conn.execute(
                "UPDATE handoff_executions SET status='success',result_json=?,error_message='',updated_at=? WHERE ticket_hash=?",
                (payload, timestamp, self.ticket_hash(ticket)),
            )

    def mark_failed(self, ticket: str, error: str, *, now: int | None = None) -> None:
        timestamp = int(time.time() if now is None else now)
        with self._connect() as conn:
            conn.execute(
                "UPDATE handoff_executions SET status='failed',error_message=?,updated_at=? WHERE ticket_hash=?",
                (str(error)[:800], timestamp, self.ticket_hash(ticket)),
            )
