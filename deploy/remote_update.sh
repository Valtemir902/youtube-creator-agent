#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_SHA="${1:-}"
if [[ -z "$TARGET_SHA" ]]; then
  echo "usage: remote_update.sh <commit-sha>" >&2
  exit 2
fi

APP_DIR="${YCA_DEPLOY_DIR:-$HOME/apps/youtube-creator-agent}"
COMPOSE_FILE="deploy/docker-compose.oracle.yml"
PREVIOUS_SHA=""
ENV_BACKUP=""
SUCCESS=0

cd "$APP_DIR"
PREVIOUS_SHA="$(git rev-parse HEAD)"

if [[ ! -f config/server.env ]]; then
  echo "Missing config/server.env on VPS" >&2
  exit 4
fi

umask 077
ENV_BACKUP="$(mktemp /tmp/yca-server-env.XXXXXX)"
cp -p config/server.env "$ENV_BACKUP"
chmod 600 "$ENV_BACKUP"

restore_on_failure() {
  local code=$?
  trap - EXIT ERR INT TERM
  if [[ "$SUCCESS" != "1" ]]; then
    echo "Deploy wrapper failed with exit code $code; restoring code and server.env" >&2
    cp -p "$ENV_BACKUP" config/server.env 2>/dev/null || true
    chmod 600 config/server.env 2>/dev/null || true
    git reset --hard "$PREVIOUS_SHA" >/dev/null 2>&1 || true
    docker compose -f "$COMPOSE_FILE" start keycloak >/dev/null 2>&1 || true
    docker compose -f "$COMPOSE_FILE" up -d --build mcp onboarding >/dev/null 2>&1 || true
  fi
  rm -f "$ENV_BACKUP" /tmp/yca-dcr-provisioner.secret /tmp/yca-remote-update-core.sh /tmp/yca-remote-update-core-patched.sh /tmp/yca-provision-dcr.sh
  exit "$code"
}
trap restore_on_failure EXIT ERR INT TERM

# Materialize the helper and original PR #30 deployment core from the exact candidate SHA.
git fetch --prune origin "$TARGET_SHA"
git show "$TARGET_SHA:deploy/provision_dcr_keycloak.sh" > /tmp/yca-provision-dcr.sh
git show "$TARGET_SHA:deploy/remote_update_core.sh" > /tmp/yca-remote-update-core.sh
chmod 700 /tmp/yca-provision-dcr.sh /tmp/yca-remote-update-core.sh

YCA_DCR_SECRET_OUT=/tmp/yca-dcr-provisioner.secret /tmp/yca-provision-dcr.sh

dcr_secret="$(tr -d '\r\n' < /tmp/yca-dcr-provisioner.secret)"
test -n "$dcr_secret"

set_env_value() {
  local key="$1" value="$2"
  if grep -q "^${key}=" config/server.env; then
    sed -i "s#^${key}=.*#${key}=${value}#" config/server.env
  else
    printf '\n%s=%s\n' "$key" "$value" >> config/server.env
  fi
}

set_env_value YCA_KEYCLOAK_ADMIN_URL "http://keycloak:8080"
set_env_value YCA_KEYCLOAK_REALM "yca"
set_env_value YCA_DCR_CLIENT_ID_PREFIX "yca-chatgpt-dcr-"
set_env_value YCA_DCR_ALLOWED_REDIRECT_HOSTS "chatgpt.com"
set_env_value YCA_DCR_PROVISIONER_CLIENT_ID "yca-dcr-provisioner"
set_env_value YCA_DCR_PROVISIONER_CLIENT_SECRET "$dcr_secret"
chmod 600 config/server.env
unset dcr_secret
rm -f /tmp/yca-dcr-provisioner.secret

# Keep the PR #30 core byte-for-byte and remove only its obsolete password-based
# bootstrap block at runtime. This limits the deploy fix to provisioning/rollback.
awk '
  BEGIN { skipping=0; found_start=0; found_end=0 }
  $0 == "# DCR clients are created only through this narrowly scoped, confidential" {
    skipping=1; found_start=1
    print "# DCR provisioner was reconciled by the deployment wrapper using the supported"
    print "# temporary bootstrap-admin service recovery flow."
    next
  }
  $0 == "# Read the fixed public OAuth client without letting grep/pipefail abort the" {
    skipping=0; found_end=1
  }
  !skipping { print }
  END { if (!found_start || !found_end) exit 42 }
' /tmp/yca-remote-update-core.sh > /tmp/yca-remote-update-core-patched.sh
chmod 700 /tmp/yca-remote-update-core-patched.sh
bash -n /tmp/yca-remote-update-core-patched.sh

/tmp/yca-remote-update-core-patched.sh "$TARGET_SHA"

# Independent post-core MCP contract check. This performs no YouTube mutation.
docker compose -f "$COMPOSE_FILE" exec -T mcp python - <<'PY'
import asyncio
from mcp import Client
from creator_service.cloud_mcp_server_management import create_server

required = {
    'get_video_details', 'get_video_transcript', 'list_channel_videos',
    'preview_video_metadata_update', 'render_video_metadata_handoff',
}

async def main():
    async with Client(create_server(), raise_exceptions=True) as client:
        result = await client.list_tools()
        names = {tool.name for tool in result.tools}
        missing = required - names
        assert not missing, sorted(missing)
        assert len(names) >= 34, len(names)
        print(f'mcp_contract=ok tools={len(names)}')

asyncio.run(main())
PY

# Exercise DCR safely with the official ChatGPT callback. No YouTube write occurs.
docker compose -f "$COMPOSE_FILE" exec -T onboarding python - <<'PY'
import json, urllib.request
payload = {
    'client_name': 'YCA deploy DCR smoke',
    'redirect_uris': ['https://chatgpt.com/connector_platform_oauth_redirect'],
    'grant_types': ['authorization_code', 'refresh_token'],
    'response_types': ['code'],
    'token_endpoint_auth_method': 'none',
    'scope': 'openid email offline_access yca:read yca:write',
}
req = urllib.request.Request(
    'http://127.0.0.1:8080/oauth/register',
    data=json.dumps(payload).encode('utf-8'),
    method='POST',
    headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
)
with urllib.request.urlopen(req, timeout=10) as response:
    body = json.loads(response.read().decode('utf-8'))
    assert response.status == 201, response.status
    cid = body.get('client_id', '')
    assert cid.startswith('yca-chatgpt-dcr-'), cid
    assert body.get('redirect_uris') == payload['redirect_uris']
    assert body.get('token_endpoint_auth_method') == 'none'
print('dcr_registration_smoke=ok')
PY

SUCCESS=1
rm -f "$ENV_BACKUP"
trap - EXIT ERR INT TERM
printf 'Safe deploy wrapper succeeded: %s\n' "$(git rev-parse HEAD)"
