from __future__ import annotations

import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DashboardAction:
    action_id: str
    tenant_id: str
    kind: str
    payload: dict[str, Any]
    secret_token: str
    expires_at: int


class DashboardActionStore:
    """Server-side vault for signed write packages used by the web dashboard.

    Approval/rollback tokens never need to be exposed to browser JavaScript. The
    browser receives only a random action_id tied to the authenticated tenant.
    """

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dashboard_actions (
                    action_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    secret_token TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dashboard_actions_expiry ON dashboard_actions(expires_at)"
            )

    def put(
        self,
        *,
        tenant_id: str,
        kind: str,
        payload: dict[str, Any],
        secret_token: str,
        ttl_seconds: int = 900,
        now: int | None = None,
    ) -> str:
        tenant_id = tenant_id.strip()
        kind = kind.strip()
        if not tenant_id or not kind or not secret_token:
            raise ValueError("tenant_id, kind e secret_token são obrigatórios.")
        timestamp = int(time.time() if now is None else now)
        action_id = secrets.token_urlsafe(24)
        expires_at = timestamp + max(60, min(3600, int(ttl_seconds)))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO dashboard_actions(action_id,tenant_id,kind,payload_json,secret_token,expires_at,used_at) VALUES(?,?,?,?,?,?,NULL)",
                (
                    action_id,
                    tenant_id,
                    kind[:80],
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    secret_token,
                    expires_at,
                ),
            )
        return action_id

    def consume(
        self,
        *,
        action_id: str,
        tenant_id: str,
        kind: str,
        now: int | None = None,
    ) -> DashboardAction:
        timestamp = int(time.time() if now is None else now)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT action_id,tenant_id,kind,payload_json,secret_token,expires_at,used_at FROM dashboard_actions WHERE action_id=?",
                (action_id.strip(),),
            ).fetchone()
            if row is None:
                raise PermissionError("Ação temporária inválida ou já removida.")
            if row["tenant_id"] != tenant_id or row["kind"] != kind:
                raise PermissionError("Ação temporária não pertence a esta sessão.")
            if row["used_at"] is not None:
                raise PermissionError("Ação temporária já utilizada.")
            if int(row["expires_at"]) < timestamp:
                conn.execute("DELETE FROM dashboard_actions WHERE action_id=?", (action_id,))
                raise PermissionError("Ação temporária expirada. Gere uma nova prévia.")
            updated = conn.execute(
                "UPDATE dashboard_actions SET used_at=? WHERE action_id=? AND used_at IS NULL",
                (timestamp, action_id),
            )
            if updated.rowcount != 1:
                raise PermissionError("Ação temporária já utilizada.")
        return DashboardAction(
            action_id=str(row["action_id"]),
            tenant_id=str(row["tenant_id"]),
            kind=str(row["kind"]),
            payload=json.loads(row["payload_json"]),
            secret_token=str(row["secret_token"]),
            expires_at=int(row["expires_at"]),
        )

    def purge_expired(self, *, now: int | None = None) -> int:
        timestamp = int(time.time() if now is None else now)
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM dashboard_actions WHERE expires_at < ? OR used_at IS NOT NULL",
                (timestamp,),
            )
            return int(cur.rowcount or 0)
