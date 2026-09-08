from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "deploy" / "remote_update.sh"
CORE = ROOT / "deploy" / "remote_update_core.sh"
PROVISIONER = ROOT / "deploy" / "provision_dcr_keycloak.sh"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_deploy_scripts_have_valid_bash_syntax():
    for path in (WRAPPER, CORE, PROVISIONER):
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_wrapper_restores_server_env_and_previous_sha_on_failure():
    text = _text(WRAPPER)
    assert 'cp -p config/server.env "$ENV_BACKUP"' in text
    assert 'cp -p "$ENV_BACKUP" config/server.env' in text
    assert 'git reset --hard "$PREVIOUS_SHA"' in text
    assert "up -d --build mcp onboarding" in text


def test_deploy_does_not_use_stale_bootstrap_password_credentials():
    text = _text(WRAPPER) + _text(PROVISIONER)
    assert "KC_BOOTSTRAP_ADMIN_USERNAME" not in text
    assert "KC_BOOTSTRAP_ADMIN_PASSWORD" not in text
    assert "bootstrap-admin service" in text
    assert "--client-secret:env" in text


def test_temporary_admin_is_created_only_with_keycloak_stopped_and_removed():
    text = _text(PROVISIONER)
    stop_at = text.index("stop keycloak")
    bootstrap_at = text.index("bootstrap-admin service")
    start_at = text.index("start keycloak", bootstrap_at)
    assert stop_at < bootstrap_at < start_at
    assert "delete clients/$tid -r master" in text


def test_provisioner_is_reconciled_to_manage_clients_without_realm_admin():
    text = _text(PROVISIONER)
    assert "serviceAccountsEnabled=true" in text
    assert "publicClient=false" in text
    assert "--cclientid realm-management --rolename manage-clients" in text
    assert 'if [ "$role" != "manage-clients" ]' in text
    assert "realm-admin is forbidden for DCR provisioner" in text


def test_secret_is_not_logged_and_client_credentials_is_verified():
    text = _text(PROVISIONER)
    assert "DCR_CLIENT_SECRET" in text
    assert "client_credentials" in text
    assert "access_token" in text
    assert 'echo "$dcr_secret"' not in text
    assert 'echo "$TEMP_SECRET"' not in text


def test_wrapper_keeps_mcp_and_dcr_smoke_checks_read_only_for_youtube():
    text = _text(WRAPPER)
    assert "len(names) >= 34" in text
    for name in (
        "get_video_details",
        "get_video_transcript",
        "list_channel_videos",
        "preview_video_metadata_update",
        "render_video_metadata_handoff",
    ):
        assert name in text
    assert "/oauth/register" in text
    assert "apply_video_metadata_update(" not in text
    assert "apply_caption_upload(" not in text
