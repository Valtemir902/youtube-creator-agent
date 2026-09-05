from cryptography.fernet import Fernet

from creator_service.onboarding_sessions import OnboardingSessionStore
from creator_service.tenant_store import EncryptionBox, TenantDatabase


def make_store(tmp_path):
    db = TenantDatabase(tmp_path / "tenants.sqlite3", EncryptionBox(Fernet.generate_key()))
    db.ensure_tenant("tenant-a")
    return OnboardingSessionStore(db)


def test_launch_is_single_use_and_becomes_session(tmp_path):
    store = make_store(tmp_path)
    launch = store.issue_launch("tenant-a", ["yca:read", "yca:write"])

    session_token, identity = store.exchange_launch(launch)
    assert identity.tenant_id == "tenant-a"
    assert set(identity.scopes) == {"yca:read", "yca:write"}
    assert store.resolve(session_token) == identity

    try:
        store.exchange_launch(launch)
    except PermissionError as exc:
        assert "utilizado" in str(exc)
    else:
        raise AssertionError("one-time onboarding launch token was accepted twice")


def test_session_can_be_revoked(tmp_path):
    store = make_store(tmp_path)
    launch = store.issue_launch("tenant-a", ["yca:read"])
    session_token, identity = store.exchange_launch(launch)
    assert identity.scopes == ("yca:read",)
    assert store.resolve(session_token) is not None

    store.revoke(session_token)
    assert store.resolve(session_token) is None


def test_unknown_scope_is_not_propagated(tmp_path):
    store = make_store(tmp_path)
    launch = store.issue_launch("tenant-a", ["admin", "yca:write"])
    _, identity = store.exchange_launch(launch)
    assert identity.scopes == ("yca:read", "yca:write")
