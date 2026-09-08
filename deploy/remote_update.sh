#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_SHA="${1:-}"
if [[ -z "$TARGET_SHA" ]]; then
  echo "usage: remote_update.sh <commit-sha>" >&2
  exit 2
fi

APP_DIR="${YCA_DEPLOY_DIR:-$HOME/apps/youtube-creator-agent}"
COMPOSE_FILE="deploy/docker-compose.oracle.yml"
LEGACY_CHATGPT_CLIENT_ID="82da41e4-4d89-4ccf-b134-c6a8b01f8453"
LEGACY_CHATGPT_REDIRECT="https://chatgpt.com/connector_platform_oauth_redirect"
MODERN_CHATGPT_REDIRECT_PATTERN="https://chatgpt.com/connector/oauth/*"
MODERN_CHATGPT_SMOKE_REDIRECT="https://chatgpt.com/connector/oauth/yca-deploy-smoke"
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

# Compatibility bridge for ChatGPT apps created before the isolated DCR fix.
# Those drafts can retain the legacy Keycloak client_id while ChatGPT now sends
# a per-connection callback under /connector/oauth/<id>. Keep the historical
# exact callback and add only the narrow, HTTPS, exact-host path wildcard that
# Keycloak supports at the end of a redirect pattern. Never allow a host wildcard.
legacy_client_id="$(sed -n 's/^YCA_CHATGPT_OAUTH_CLIENT_ID=//p' config/server.env | tail -n1 | tr -d '\r' || true)"
if [[ -z "$legacy_client_id" ]]; then
  legacy_client_id="$LEGACY_CHATGPT_CLIENT_ID"
fi

docker compose -f "$COMPOSE_FILE" exec -T \
  -e DCR_CLIENT_ID="yca-dcr-provisioner" \
  -e DCR_CLIENT_SECRET="$dcr_secret" \
  -e LEGACY_CLIENT_ID="$legacy_client_id" \
  -e LEGACY_REDIRECT="$LEGACY_CHATGPT_REDIRECT" \
  -e MODERN_REDIRECT_PATTERN="$MODERN_CHATGPT_REDIRECT_PATTERN" \
  onboarding python - <<'PY'
import json
import os
import urllib.parse
import urllib.request

base = "http://keycloak:8080"
realm = "yca"

form = urllib.parse.urlencode(
    {
        "grant_type": "client_credentials",
        "client_id": os.environ["DCR_CLIENT_ID"],
        "client_secret": os.environ["DCR_CLIENT_SECRET"],
    }
).encode("ascii")
with urllib.request.urlopen(
    urllib.request.Request(
        f"{base}/realms/{realm}/protocol/openid-connect/token",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    ),
    timeout=10,
) as response:
    token = json.loads(response.read().decode("utf-8"))["access_token"]

headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
query = urllib.parse.urlencode({"clientId": os.environ["LEGACY_CLIENT_ID"], "exact": "true"})
with urllib.request.urlopen(
    urllib.request.Request(f"{base}/admin/realms/{realm}/clients?{query}", headers=headers),
    timeout=10,
) as response:
    matches = json.loads(response.read().decode("utf-8"))
assert len(matches) == 1, f"legacy_client_count={len(matches)}"
internal_id = matches[0]["id"]

with urllib.request.urlopen(
    urllib.request.Request(f"{base}/admin/realms/{realm}/clients/{internal_id}", headers=headers),
    timeout=10,
) as response:
    representation = json.loads(response.read().decode("utf-8"))

required = {os.environ["LEGACY_REDIRECT"], os.environ["MODERN_REDIRECT_PATTERN"]}
redirects = set(representation.get("redirectUris") or [])
if not required.issubset(redirects):
    representation["redirectUris"] = sorted(redirects | required)
    body = json.dumps(representation).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/admin/realms/{realm}/clients/{internal_id}",
        data=body,
        method="PUT",
        headers={**headers, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status in (200, 204), response.status

with urllib.request.urlopen(
    urllib.request.Request(f"{base}/admin/realms/{realm}/clients/{internal_id}", headers=headers),
    timeout=10,
) as response:
    verified = json.loads(response.read().decode("utf-8"))
verified_redirects = set(verified.get("redirectUris") or [])
assert required.issubset(verified_redirects), sorted(verified_redirects)
assert "*" not in verified_redirects
assert "https://chatgpt.com/*" not in verified_redirects
print("legacy_chatgpt_redirect_compat=ok")
PY

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

# Independent post-core MCP contract check. Use the exact production server
# factory from cloud_mcp_server.py, which includes the responsible handoff layer.
# Verifying only the management layer would incorrectly omit the 34th tool.
docker compose -f "$COMPOSE_FILE" exec -T mcp python - <<'PY'
import asyncio
from mcp import Client
from creator_service.cloud_mcp_server_responsible import create_server

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
        resources = await client.list_resources()
        resource_items = getattr(resources, 'resources', resources)
        resource_uris = {str(item.uri) for item in resource_items}
        assert 'ui://youtube-creator-agent/handoff-v1.html' in resource_uris, resource_uris
        print(f'mcp_contract=ok tools={len(names)} resources={len(resource_uris)}')

asyncio.run(main())
PY

# Exercise DCR safely with both the historical and modern ChatGPT callback
# shapes. DCR stores the exact callback on its isolated client; no wildcard is
# accepted from the DCR payload itself and no YouTube write occurs.
docker compose -f "$COMPOSE_FILE" exec -T onboarding python - <<'PY'
import json
import urllib.request

for suffix, redirect in (
    ("legacy", "https://chatgpt.com/connector_platform_oauth_redirect"),
    ("modern", "https://chatgpt.com/connector/oauth/yca-deploy-smoke"),
):
    payload = {
        'client_name': f'YCA deploy DCR smoke {suffix}',
        'redirect_uris': [redirect],
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
print('dcr_registration_smoke=ok legacy+modern')
PY

# Verify the legacy public client also accepts a modern per-connection callback.
# This is the compatibility path used by ChatGPT drafts created before DCR was
# fixed. A 200 login page proves Keycloak accepted redirect_uri; no login occurs.
docker compose -f "$COMPOSE_FILE" exec -T \
  -e LEGACY_CLIENT_ID="$legacy_client_id" \
  -e MODERN_SMOKE_REDIRECT="$MODERN_CHATGPT_SMOKE_REDIRECT" \
  onboarding python - <<'PY'
import base64
import hashlib
import os
import secrets
import urllib.parse
import urllib.request

verifier = secrets.token_urlsafe(48)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
params = {
    'response_type': 'code',
    'client_id': os.environ['LEGACY_CLIENT_ID'],
    'redirect_uri': os.environ['MODERN_SMOKE_REDIRECT'],
    'scope': 'openid email offline_access yca:read yca:write',
    'state': 'modern-redirect-smoke',
    'code_challenge': challenge,
    'code_challenge_method': 'S256',
}
url = 'http://keycloak:8080/realms/yca/protocol/openid-connect/auth?' + urllib.parse.urlencode(params)
request = urllib.request.Request(url, headers={'Host': 'auth.silvadigitaltech.com', 'X-Forwarded-Proto': 'https'})
with urllib.request.urlopen(request, timeout=10) as response:
    body = response.read(8192).decode('utf-8', 'replace').lower()
    assert response.status == 200
    assert 'invalid parameter: redirect_uri' not in body
    assert 'invalid_redirect_uri' not in body
    assert 'invalid_scope' not in body
print('legacy_modern_redirect_authorization=ok')
PY

SUCCESS=1
rm -f "$ENV_BACKUP"
trap - EXIT ERR INT TERM
printf 'Safe deploy wrapper succeeded: %s\n' "$(git rev-parse HEAD)"
