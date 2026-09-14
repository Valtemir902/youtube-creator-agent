from google.auth.exceptions import RefreshError

from creator_service import channel_accounts
from creator_service.cloud_runtime import GOOGLE_SECRET_NAME


class _DB:
    def __init__(self):
        self.values = {("tenant", GOOGLE_SECRET_NAME): '{"refresh_token":"stale"}'}
        self.writes = []

    def get_secret(self, tenant_id, name):
        return self.values.get((tenant_id, name))

    def put_secret(self, tenant_id, name, value):
        self.writes.append((tenant_id, name, value))
        self.values[(tenant_id, name)] = value


def test_revoked_token_does_not_block_fresh_google_oauth_preflight(monkeypatch):
    db = _DB()

    def revoked(_raw):
        raise RefreshError('invalid_grant: Token has been expired or revoked.')

    monkeypatch.setattr(channel_accounts, '_channel_snapshot_from_raw', revoked)
    assert channel_accounts.capture_current_channel(db, 'tenant') is None
    assert db.writes == []
    assert db.get_secret('tenant', GOOGLE_SECRET_NAME) is not None


def test_non_auth_snapshot_failures_are_not_hidden(monkeypatch):
    db = _DB()

    def corrupt(_raw):
        raise RuntimeError('credential payload corrupt')

    monkeypatch.setattr(channel_accounts, '_channel_snapshot_from_raw', corrupt)
    try:
        channel_accounts.capture_current_channel(db, 'tenant')
    except RuntimeError as exc:
        assert 'corrupt' in str(exc)
    else:
        raise AssertionError('non-auth corruption must remain visible')
