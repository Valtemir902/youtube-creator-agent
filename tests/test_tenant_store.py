from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet

from src.creator_service.tenant_store import (
    EncryptionBox,
    TenantCredentialStore,
    TenantDatabase,
    TenantStoreError,
    validate_tenant_id,
)


def _db(tmp_path):
    return TenantDatabase(tmp_path / "tenants.sqlite3", EncryptionBox(Fernet.generate_key()))


def test_tenant_secrets_are_isolated_and_encrypted(tmp_path):
    db = _db(tmp_path)
    a = TenantCredentialStore(db, "cliente-a")
    b = TenantCredentialStore(db, "cliente-b")
    a.save_key("gemini", "segredo-a")
    b.save_key("gemini", "segredo-b")

    assert a.get_key("gemini") == "segredo-a"
    assert b.get_key("gemini") == "segredo-b"

    raw = (tmp_path / "tenants.sqlite3").read_bytes()
    assert b"segredo-a" not in raw
    assert b"segredo-b" not in raw


def test_wrong_encryption_key_cannot_decrypt(tmp_path):
    path = tmp_path / "tenants.sqlite3"
    db1 = TenantDatabase(path, EncryptionBox(Fernet.generate_key()))
    db1.put_secret("cliente-a", "google", "token-super-secreto")

    db2 = TenantDatabase(path, EncryptionBox(Fernet.generate_key()))
    with pytest.raises(TenantStoreError, match="descriptografar"):
        db2.get_secret("cliente-a", "google")


def test_oauth_state_is_one_time_and_expires(tmp_path):
    db = _db(tmp_path)
    now = int(time.time())
    db.save_oauth_state("cliente-a", "state-1", now + 60)
    assert db.consume_oauth_state("state-1", now) == "cliente-a"

    with pytest.raises(TenantStoreError, match="já foi utilizado"):
        db.consume_oauth_state("state-1", now + 1)

    db.save_oauth_state("cliente-a", "state-2", now - 1)
    with pytest.raises(TenantStoreError, match="expirou"):
        db.consume_oauth_state("state-2", now)


def test_oauth_state_concurrent_callbacks_only_one_consumes(tmp_path):
    db = _db(tmp_path)
    now = int(time.time())
    db.save_oauth_state("cliente-a", "state-race", now + 60)
    barrier = threading.Barrier(2)

    def consume():
        barrier.wait(timeout=5)
        try:
            return ("ok", db.consume_oauth_state("state-race", now))
        except TenantStoreError as exc:
            return ("error", str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: consume(), range(2)))

    successes = [value for status, value in results if status == "ok"]
    failures = [value for status, value in results if status == "error"]
    assert successes == ["cliente-a"]
    assert len(failures) == 1
    assert "já foi utilizado" in failures[0]


def test_tenant_id_rejects_path_traversal():
    assert validate_tenant_id("cliente_123") == "cliente_123"
    for invalid in ("../outro", "cliente/filho", "", " espaço"):
        with pytest.raises(TenantStoreError):
            validate_tenant_id(invalid)
