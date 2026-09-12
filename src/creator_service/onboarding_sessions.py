from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Iterable

from .tenant_store import TenantDatabase, validate_tenant_id


@dataclass(frozen=True)
class WebIdentity:
    tenant_id: str
    scopes: tuple[str, ...]


class OnboardingSessionStore:
    """One-time launch links and server-side browser sessions.

    Raw tokens are never persisted. Only SHA-256 digests are stored. A launch
    token is single-use and becomes a separate browser session token after the
    initial redirect. Direct browser login can also mint the same isolated
    server-side session after successful OIDC authentication.
    """

    def __init__(self, db: TenantDatabase):
        self.db = db
        self._init_db()

    def _init_db(self) -> None:
        with self.db._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS onboarding_launches (
                    token_hash TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    consumed_at INTEGER,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
                );
                CREATE TABLE IF NOT EXISTS onboarding_web_sessions (
                    token_hash TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER,
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
                );
                CREATE INDEX IF NOT EXISTS idx_onboarding_sessions_tenant
                    ON onboarding_web_sessions(tenant_id, expires_at);
                """
            )

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _clean_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
        allowed = {"yca:read", "yca:write"}
        clean = sorted({str(scope).strip() for scope in scopes if str(scope).strip() in allowed})
        if "yca:read" not in clean:
            clean.insert(0, "yca:read")
        return tuple(clean)

    @staticmethod
    def _encode_scopes(scopes: tuple[str, ...]) -> str:
        return " ".join(scopes)

    @staticmethod
    def _decode_scopes(raw: str) -> tuple[str, ...]:
        return tuple(item for item in raw.split() if item)

    def issue_launch(self, tenant_id: str, scopes: Iterable[str], ttl_seconds: int = 600) -> str:
        tenant_id = self.db.ensure_tenant(validate_tenant_id(tenant_id))
        ttl = max(60, min(1800, int(ttl_seconds)))
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        clean_scopes = self._clean_scopes(scopes)
        with self.db._connect() as conn:
            conn.execute(
                "INSERT INTO onboarding_launches(token_hash,tenant_id,scopes,expires_at,consumed_at,created_at) "
                "VALUES(?,?,?,?,NULL,?)",
                (self._hash(token), tenant_id, self._encode_scopes(clean_scopes), now + ttl, now),
            )
            conn.execute("DELETE FROM onboarding_launches WHERE expires_at < ? OR consumed_at IS NOT NULL", (now - 3600,))
        return token

    def issue_session(
        self,
        tenant_id: str,
        scopes: Iterable[str] = ("yca:read", "yca:write"),
        session_ttl_seconds: int = 28800,
    ) -> tuple[str, WebIdentity]:
        tenant_id = self.db.ensure_tenant(validate_tenant_id(tenant_id))
        clean_scopes = self._clean_scopes(scopes)
        scopes_raw = self._encode_scopes(clean_scopes)
        now = int(time.time())
        session_ttl = max(900, min(86400, int(session_ttl_seconds)))
        session_token = secrets.token_urlsafe(48)
        with self.db._connect() as conn:
            conn.execute(
                "INSERT INTO onboarding_web_sessions(token_hash,tenant_id,scopes,expires_at,revoked_at,created_at,last_seen_at) "
                "VALUES(?,?,?,?,NULL,?,?)",
                (self._hash(session_token), tenant_id, scopes_raw, now + session_ttl, now, now),
            )
            conn.execute(
                "DELETE FROM onboarding_web_sessions WHERE expires_at < ? OR revoked_at IS NOT NULL",
                (now - 86400,),
            )
        return session_token, WebIdentity(tenant_id, clean_scopes)

    def exchange_launch(self, launch_token: str, session_ttl_seconds: int = 28800) -> tuple[str, WebIdentity]:
        if not launch_token:
            raise PermissionError("Token de onboarding ausente.")
        now = int(time.time())
        digest = self._hash(launch_token)
        with self.db._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT tenant_id, scopes, expires_at, consumed_at FROM onboarding_launches WHERE token_hash=?",
                (digest,),
            ).fetchone()
            if not row:
                raise PermissionError("Link de onboarding inválido.")
            tenant_id, scopes_raw, expires_at, consumed_at = row
            if consumed_at is not None:
                raise PermissionError("Este link de onboarding já foi utilizado.")
            if int(expires_at) < now:
                raise PermissionError("Este link de onboarding expirou.")
            updated = conn.execute(
                "UPDATE onboarding_launches SET consumed_at=? WHERE token_hash=? AND consumed_at IS NULL",
                (now, digest),
            ).rowcount
            if updated != 1:
                raise PermissionError("Este link de onboarding já foi utilizado.")

            session_token = secrets.token_urlsafe(48)
            session_ttl = max(900, min(86400, int(session_ttl_seconds)))
            conn.execute(
                "INSERT INTO onboarding_web_sessions(token_hash,tenant_id,scopes,expires_at,revoked_at,created_at,last_seen_at) "
                "VALUES(?,?,?,?,NULL,?,?)",
                (self._hash(session_token), tenant_id, scopes_raw, now + session_ttl, now, now),
            )
        identity = WebIdentity(str(tenant_id), self._decode_scopes(str(scopes_raw)))
        return session_token, identity

    def resolve(self, session_token: str) -> WebIdentity | None:
        if not session_token:
            return None
        now = int(time.time())
        digest = self._hash(session_token)
        with self.db._connect() as conn:
            row = conn.execute(
                "SELECT tenant_id, scopes, expires_at, revoked_at FROM onboarding_web_sessions WHERE token_hash=?",
                (digest,),
            ).fetchone()
            if not row:
                return None
            tenant_id, scopes_raw, expires_at, revoked_at = row
            if revoked_at is not None or int(expires_at) < now:
                return None
            conn.execute(
                "UPDATE onboarding_web_sessions SET last_seen_at=? WHERE token_hash=?",
                (now, digest),
            )
        self.db.ensure_tenant(str(tenant_id))
        return WebIdentity(str(tenant_id), self._decode_scopes(str(scopes_raw)))

    def revoke(self, session_token: str) -> None:
        if not session_token:
            return
        now = int(time.time())
        with self.db._connect() as conn:
            conn.execute(
                "UPDATE onboarding_web_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (now, self._hash(session_token)),
            )
