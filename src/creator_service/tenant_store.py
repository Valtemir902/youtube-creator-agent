from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


_TENANT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")


class TenantStoreError(RuntimeError):
    pass


def validate_tenant_id(tenant_id: str) -> str:
    value = (tenant_id or "").strip()
    if not _TENANT_RE.fullmatch(value):
        raise TenantStoreError("Identificador de cliente inválido.")
    return value


class EncryptionBox:
    """Fernet envelope encryption for tenant secrets at rest."""

    def __init__(self, key: str | bytes):
        if isinstance(key, str):
            key = key.encode("ascii")
        try:
            self._fernet = Fernet(key)
        except Exception as exc:
            raise TenantStoreError(
                "YCA_DATA_ENCRYPTION_KEY inválida. Use uma chave Fernet urlsafe-base64 de 32 bytes."
            ) from exc

    def encrypt_text(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt_text(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise TenantStoreError("Falha ao descriptografar segredo do cliente.") from exc


def encryption_box_from_env() -> EncryptionBox:
    raw = os.environ.get("YCA_DATA_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise TenantStoreError("YCA_DATA_ENCRYPTION_KEY é obrigatória no modo cloud.")
    return EncryptionBox(raw)


class TenantDatabase:
    def __init__(self, path: str | Path, box: EncryptionBox):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.box = box
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS tenant_secrets (
                    tenant_id TEXT NOT NULL,
                    secret_name TEXT NOT NULL,
                    encrypted_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(tenant_id, secret_name),
                    FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
                );
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state_hash TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    consumed_at INTEGER,
                    FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
                );
                """
            )

    def ensure_tenant(self, tenant_id: str) -> str:
        tenant_id = validate_tenant_id(tenant_id)
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO tenants(tenant_id) VALUES (?)", (tenant_id,))
            row = conn.execute("SELECT enabled FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
        if not row or int(row[0]) != 1:
            raise TenantStoreError("Cliente inexistente ou desativado.")
        return tenant_id

    def put_secret(self, tenant_id: str, name: str, value: str) -> None:
        tenant_id = self.ensure_tenant(tenant_id)
        name = name.strip()
        if not name or not value:
            raise TenantStoreError("Nome e valor do segredo são obrigatórios.")
        encrypted = self.box.encrypt_text(value)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tenant_secrets(tenant_id,secret_name,encrypted_value,updated_at) "
                "VALUES(?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(tenant_id,secret_name) DO UPDATE SET "
                "encrypted_value=excluded.encrypted_value, updated_at=CURRENT_TIMESTAMP",
                (tenant_id, name, encrypted),
            )

    def get_secret(self, tenant_id: str, name: str) -> str | None:
        tenant_id = self.ensure_tenant(tenant_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT encrypted_value FROM tenant_secrets WHERE tenant_id=? AND secret_name=?",
                (tenant_id, name),
            ).fetchone()
        return self.box.decrypt_text(row[0]) if row else None

    def delete_secret(self, tenant_id: str, name: str) -> None:
        tenant_id = self.ensure_tenant(tenant_id)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM tenant_secrets WHERE tenant_id=? AND secret_name=?",
                (tenant_id, name),
            )

    @staticmethod
    def state_hash(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    def save_oauth_state(self, tenant_id: str, state: str, expires_at: int) -> None:
        tenant_id = self.ensure_tenant(tenant_id)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO oauth_states(state_hash,tenant_id,expires_at,consumed_at) VALUES(?,?,?,NULL)",
                (self.state_hash(state), tenant_id, int(expires_at)),
            )

    def consume_oauth_state(self, state: str, now: int) -> str:
        digest = self.state_hash(state)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT tenant_id, expires_at, consumed_at FROM oauth_states WHERE state_hash=?",
                (digest,),
            ).fetchone()
            if not row:
                raise TenantStoreError("Estado OAuth inválido.")
            tenant_id, expires_at, consumed_at = row
            if consumed_at is not None:
                raise TenantStoreError("Estado OAuth já foi utilizado.")
            if int(expires_at) < int(now):
                raise TenantStoreError("Estado OAuth expirou.")
            conn.execute(
                "UPDATE oauth_states SET consumed_at=? WHERE state_hash=? AND consumed_at IS NULL",
                (int(now), digest),
            )
        return str(tenant_id)


@dataclass
class TenantCredentialStore:
    """AIRuntime-compatible encrypted API-key store scoped to one tenant."""

    db: TenantDatabase
    tenant_id: str

    @staticmethod
    def _name(provider: str) -> str:
        provider = provider.strip().lower()
        if not provider:
            raise TenantStoreError("Provedor de IA inválido.")
        return f"ai:{provider}:api_key"

    def set_session_key(self, provider: str, api_key: str) -> None:
        # Cloud workers are stateless: even a session key must be scoped to the
        # authenticated tenant. A future Redis adapter can replace this without
        # changing AIRuntime.
        self.save_key(provider, api_key)

    def save_key(self, provider: str, api_key: str) -> None:
        if not api_key:
            raise TenantStoreError("A chave API não pode ser vazia.")
        self.db.put_secret(self.tenant_id, self._name(provider), api_key)

    def get_key(self, provider: str) -> str | None:
        return self.db.get_secret(self.tenant_id, self._name(provider))

    def delete_key(self, provider: str) -> None:
        self.db.delete_secret(self.tenant_id, self._name(provider))


def tenant_database_from_env(root: str | Path | None = None) -> TenantDatabase:
    root_path = Path(root or os.environ.get("YCA_ROOT") or Path.cwd()).resolve()
    db_path = Path(os.environ.get("YCA_TENANT_DB", root_path / "data" / "tenants.sqlite3"))
    return TenantDatabase(db_path, encryption_box_from_env())
