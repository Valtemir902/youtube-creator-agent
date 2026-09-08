#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_SHA="${1:-}"
if [[ -z "$TARGET_SHA" ]]; then
  echo "usage: remote_update.sh <commit-sha>" >&2
  exit 2
fi

APP_DIR="${YCA_DEPLOY_DIR:-$HOME/apps/youtube-creator-agent}"
COMPOSE_FILE="deploy/docker-compose.oracle.yml"
BACKCHANNEL_VALUE="http://keycloak:8080/realms/yca"
INTROSPECTION_VALUE="http://keycloak:8080/realms/yca/protocol/openid-connect/token/introspect"
FALLBACK_CHATGPT_CLIENT_ID="82da41e4-4d89-4ccf-b134-c6a8b01f8453"
DESIRED_LOGIN_THEME="keycloak.v2"

cd "$APP_DIR"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Refusing deploy: tracked files have local modifications in $APP_DIR" >&2
  git status --short
  exit 3
fi

PREVIOUS_SHA="$(git rev-parse HEAD)"
ROLLBACK_NEEDED=1

rollback() {
  local code=$?
  trap - ERR
  if [[ "$ROLLBACK_NEEDED" == "1" ]]; then
    echo "Deploy failed with exit code $code. Rolling back code to $PREVIOUS_SHA" >&2
    git reset --hard "$PREVIOUS_SHA" || true
    docker compose -f "$COMPOSE_FILE" up -d --build mcp onboarding || true
  fi
  exit "$code"
}
trap rollback ERR

wait_for_url() {
  local url="$1" label="$2" attempts="${3:-30}" delay="${4:-2}"
  local i code
  for ((i=1; i<=attempts; i++)); do
    code="$(curl --show-error --silent --location --max-time 10 --output /dev/null --write-out '%{http_code}' "$url" || true)"
    if [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
      echo "$label ready (HTTP $code) on attempt $i/$attempts"
      return 0
    fi
    echo "$label not ready yet (HTTP ${code:-000}), attempt $i/$attempts"
    sleep "$delay"
  done
  echo "$label failed to become ready: $url" >&2
  return 1
}

set_env_value() {
  local key="$1" value="$2"
  if grep -q "^${key}=" config/server.env; then
    sed -i "s#^${key}=.*#${key}=${value}#" config/server.env
  else
    printf '\n%s=%s\n' "$key" "$value" >> config/server.env
  fi
}

echo "Deploying commit $TARGET_SHA (previous: $PREVIOUS_SHA)"
git fetch --prune origin "$TARGET_SHA"
git checkout feat/web-dashboard-v1
git reset --hard "$TARGET_SHA"

if [[ ! -f config/server.env ]]; then
  echo "Missing config/server.env on VPS" >&2
  exit 4
fi

echo "[oauth] forcing private Docker backchannels"
set_env_value YCA_WEB_OIDC_BACKCHANNEL_BASE_URL "$BACKCHANNEL_VALUE"
set_env_value YCA_AUTH_INTROSPECTION_URL "$INTROSPECTION_VALUE"

# DCR clients are created only through this narrowly scoped, confidential
# Keycloak service account. Its secret stays solely in server.env on the VPS.
echo "[oauth] provisioning least-privilege DCR service account"
dcr_client_id="yca-dcr-provisioner"
set_env_value YCA_KEYCLOAK_ADMIN_URL "http://keycloak:8080"
set_env_value YCA_KEYCLOAK_REALM "yca"
set_env_value YCA_DCR_CLIENT_ID_PREFIX "yca-chatgpt-dcr-"
set_env_value YCA_DCR_ALLOWED_REDIRECT_HOSTS "chatgpt.com"
set_env_value YCA_DCR_PROVISIONER_CLIENT_ID "$dcr_client_id"
chmod 600 config/server.env

compose="docker compose -f $COMPOSE_FILE"
$compose exec -T keycloak sh -lc '
  set -eu
  k=/opt/keycloak/bin/kcadm.sh
  "$k" config credentials --server http://localhost:8080 --realm master \
    --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null
  id="$("$k" get clients -r yca -q clientId=yca-dcr-provisioner | sed -n "s/.*\"id\" : \"\([^\"]*\)\".*/\1/p" | head -n1)"
  if [ -z "$id" ]; then
    "$k" create clients -r yca -s clientId=yca-dcr-provisioner -s enabled=true \
      -s publicClient=false -s serviceAccountsEnabled=true -s standardFlowEnabled=false \
      -s directAccessGrantsEnabled=false -s implicitFlowEnabled=false >/dev/null
    id="$("$k" get clients -r yca -q clientId=yca-dcr-provisioner | sed -n "s/.*\"id\" : \"\([^\"]*\)\".*/\1/p" | head -n1)"
  fi
  test -n "$id"
  uid="$("$k" get clients/$id/service-account-user -r yca | sed -n "s/.*\"id\" : \"\([^\"]*\)\".*/\1/p" | head -n1)"
  test -n "$uid"
  "$k" add-roles -r yca --uid "$uid" --cclientid realm-management --rolename manage-clients
  if "$k" get users/$uid/role-mappings/realm -r yca | grep -q '"name" : "realm-admin"'; then
    echo "DCR provisioner must not have realm-admin" >&2; exit 1
  fi
  "$k" get clients/$id/client-secret -r yca | sed -n "s/.*\"value\" : \"\([^\"]*\)\".*/\1/p" | head -n1
' > /tmp/yca-dcr-secret
dcr_secret="$(tr -d '\r\n' </tmp/yca-dcr-secret)"
rm -f /tmp/yca-dcr-secret
test -n "$dcr_secret"
set_env_value YCA_DCR_PROVISIONER_CLIENT_SECRET "$dcr_secret"
chmod 600 config/server.env
echo "[oauth] verifying DCR provisioner client_credentials"
$compose exec -T -e DCR_CLIENT_ID="$dcr_client_id" -e DCR_CLIENT_SECRET="$dcr_secret" onboarding python - <<'PY'
import json, os, urllib.parse, urllib.request
body=urllib.parse.urlencode({"grant_type":"client_credentials","client_id":os.environ["DCR_CLIENT_ID"],"client_secret":os.environ["DCR_CLIENT_SECRET"]}).encode()
request=urllib.request.Request("http://keycloak:8080/realms/yca/protocol/openid-connect/token", data=body, headers={"Content-Type":"application/x-www-form-urlencoded"})
with urllib.request.urlopen(request, timeout=8) as response:
    token=json.loads(response.read().decode()).get("access_token")
    assert response.status == 200 and token
print("dcr_provisioner_client_credentials=ok")
PY

# Read the fixed public OAuth client without letting grep/pipefail abort the
# deploy when an older server.env does not yet contain the variable.
chatgpt_client_id="$(sed -n 's/^YCA_CHATGPT_OAUTH_CLIENT_ID=//p' config/server.env | tail -n1 | tr -d '\r' || true)"
if [[ -z "$chatgpt_client_id" ]]; then
  chatgpt_client_id="$(docker compose -f "$COMPOSE_FILE" exec -T onboarding sh -lc 'printf %s "${YCA_CHATGPT_OAUTH_CLIENT_ID:-}"' 2>/dev/null || true)"
fi
if [[ -z "$chatgpt_client_id" ]]; then
  chatgpt_client_id="$FALLBACK_CHATGPT_CLIENT_ID"
  set_env_value YCA_CHATGPT_OAUTH_CLIENT_ID "$chatgpt_client_id"
  echo "[oauth] restored fixed ChatGPT public-client identifier in server.env"
else
  echo "[oauth] fixed ChatGPT public-client identifier found"
fi

# One idempotent migration creates the custom scopes and attaches them to the
# fixed public client. yca:read is default; yca:write remains optional.
echo "[oauth] repairing Keycloak custom scopes"
migration_result="$({ docker compose -f "$COMPOSE_FILE" exec -T -e CHATGPT_CLIENT_ID="$chatgpt_client_id" keycloak-db sh -lc 'set -eu; psql -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v chatgpt_client_id="$CHATGPT_CLIENT_ID"' <<'SQL'
WITH realm_row AS (
  SELECT id FROM realm WHERE name='yca'
), target AS (
  SELECT c.id AS client_pk, r.id AS realm_pk
  FROM client c JOIN realm r ON r.id=c.realm_id
  WHERE r.name='yca' AND c.client_id=:'chatgpt_client_id'
), new_read AS (
  INSERT INTO client_scope (id, name, realm_id, description, protocol)
  SELECT md5(random()::text || clock_timestamp()::text), 'yca:read', id,
         'Read access to the authenticated YouTube Creator Agent tenant', 'openid-connect'
  FROM realm_row
  WHERE NOT EXISTS (
    SELECT 1 FROM client_scope cs JOIN realm r ON r.id=cs.realm_id
    WHERE r.name='yca' AND cs.name='yca:read'
  )
  RETURNING 1
), new_write AS (
  INSERT INTO client_scope (id, name, realm_id, description, protocol)
  SELECT md5(random()::text || clock_timestamp()::text), 'yca:write', id,
         'Write access to explicitly approved YouTube Creator Agent actions', 'openid-connect'
  FROM realm_row
  WHERE NOT EXISTS (
    SELECT 1 FROM client_scope cs JOIN realm r ON r.id=cs.realm_id
    WHERE r.name='yca' AND cs.name='yca:write'
  )
  RETURNING 1
), add_read AS (
  INSERT INTO client_scope_client (client_id, scope_id, default_scope)
  SELECT t.client_pk, cs.id, TRUE
  FROM target t
  JOIN client_scope cs ON cs.realm_id=t.realm_pk AND cs.name='yca:read'
  WHERE NOT EXISTS (
    SELECT 1 FROM client_scope_client x WHERE x.client_id=t.client_pk AND x.scope_id=cs.id
  )
  RETURNING 1
), add_write AS (
  INSERT INTO client_scope_client (client_id, scope_id, default_scope)
  SELECT t.client_pk, cs.id, FALSE
  FROM target t
  JOIN client_scope cs ON cs.realm_id=t.realm_pk AND cs.name='yca:write'
  WHERE NOT EXISTS (
    SELECT 1 FROM client_scope_client x WHERE x.client_id=t.client_pk AND x.scope_id=cs.id
  )
  RETURNING 1
)
SELECT
  (SELECT count(*) FROM target) || '|' ||
  ((SELECT count(*) FROM new_read) + (SELECT count(*) FROM new_write)) || '|' ||
  ((SELECT count(*) FROM add_read) + (SELECT count(*) FROM add_write));
SQL
} | tr -d '\r' | tail -n1)"

if [[ ! "$migration_result" =~ ^1\|[0-9]+\|[0-9]+$ ]]; then
  echo "OAuth migration did not resolve exactly one fixed ChatGPT client: $migration_result" >&2
  exit 5
fi
scope_created="$(cut -d'|' -f2 <<<"$migration_result")"
assignment_created="$(cut -d'|' -f3 <<<"$migration_result")"
echo "[oauth] scope migration verified (created scopes=$scope_created, assignments=$assignment_created)"

if (( scope_created > 0 || assignment_created > 0 )); then
  echo "[oauth] restarting Keycloak once to clear cached realm/client metadata"
  docker compose -f "$COMPOSE_FILE" restart keycloak
  wait_for_url "https://auth.silvadigitaltech.com/realms/yca/.well-known/openid-configuration" "public keycloak after OAuth repair" 45 2
fi

echo "[deploy] rebuilding application services"
docker compose -f "$COMPOSE_FILE" up -d --build mcp onboarding
docker compose -f "$COMPOSE_FILE" ps mcp onboarding keycloak

echo "[smoke] internal OIDC discovery"
docker compose -f "$COMPOSE_FILE" exec -T onboarding python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://keycloak:8080/realms/yca/.well-known/openid-configuration', timeout=8) as r:
    assert r.status == 200
print('keycloak_backchannel=ok')
PY

echo "[smoke] RFC7662 introspection through private Docker network"
docker compose -f "$COMPOSE_FILE" exec -T mcp python - <<'PY'
import base64, json, os, urllib.parse, urllib.request
endpoint=os.environ['YCA_AUTH_INTROSPECTION_URL']
assert endpoint == 'http://keycloak:8080/realms/yca/protocol/openid-connect/token/introspect', endpoint
cid=os.environ['YCA_AUTH_INTROSPECTION_CLIENT_ID']
secret=os.environ['YCA_AUTH_INTROSPECTION_CLIENT_SECRET']
body=urllib.parse.urlencode({'token':'deployment-smoke-invalid-token'}).encode('ascii')
basic=base64.b64encode(f'{cid}:{secret}'.encode()).decode('ascii')
req=urllib.request.Request(endpoint,data=body,method='POST',headers={'Authorization':f'Basic {basic}','Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'})
with urllib.request.urlopen(req,timeout=8) as r:
    payload=json.loads(r.read().decode())
    assert r.status == 200 and payload.get('active') is False, payload
print('mcp_introspection_backchannel=ok')
PY

echo "[smoke] Keycloak accepts both YCA scopes for ChatGPT PKCE client"
docker compose -f "$COMPOSE_FILE" exec -T onboarding python - <<'PY'
import base64, hashlib, os, secrets, urllib.parse, urllib.request
cid=os.environ['YCA_CHATGPT_OAUTH_CLIENT_ID']
verifier=secrets.token_urlsafe(48)
challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
params={
  'response_type':'code',
  'client_id':cid,
  'redirect_uri':'https://chatgpt.com/connector_platform_oauth_redirect',
  'scope':'openid email offline_access yca:read yca:write',
  'state':'deploy-smoke',
  'code_challenge':challenge,
  'code_challenge_method':'S256',
}
url='http://keycloak:8080/realms/yca/protocol/openid-connect/auth?'+urllib.parse.urlencode(params)
req=urllib.request.Request(url,headers={'Host':'auth.silvadigitaltech.com','X-Forwarded-Proto':'https'})
with urllib.request.urlopen(req,timeout=8) as r:
    body=r.read(8192).decode('utf-8','replace').lower()
    assert r.status == 200
    assert 'invalid_scope' not in body
print('keycloak_custom_scopes=ok')
PY

# Theme is cosmetic. Keep its repair best-effort and never let a stale bootstrap
# admin account break authentication deployment.
theme_updated=0
current_theme="$({ docker compose -f "$COMPOSE_FILE" exec -T keycloak-db sh -lc 'psql -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT COALESCE(login_theme, '') FROM realm WHERE name='yca';
SQL
} | tr -d '\r' | tail -n1)"
if [[ "$current_theme" != "$DESIRED_LOGIN_THEME" ]]; then
  set +e
  db_result="$({ docker compose -f "$COMPOSE_FILE" exec -T keycloak-db sh -lc 'psql -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
UPDATE realm SET login_theme='keycloak.v2' WHERE name='yca' AND login_theme IS DISTINCT FROM 'keycloak.v2';
SELECT COALESCE(login_theme, '') FROM realm WHERE name='yca';
SQL
  } 2>&1)"
  db_code=$?
  set -e
  if [[ "$db_code" == "0" && "${db_result##*$'\n'}" == "$DESIRED_LOGIN_THEME" ]]; then
    theme_updated=1
    echo "[theme] login theme set to $DESIRED_LOGIN_THEME"
  else
    echo "[theme] warning: cosmetic theme repair skipped" >&2
  fi
fi

wait_for_url "https://auth.silvadigitaltech.com/realms/yca/.well-known/openid-configuration" "public keycloak" 30 2
wait_for_url "https://creator.silvadigitaltech.com/health" "creator health" 30 2
wait_for_url "https://creator.silvadigitaltech.com/ready" "creator readiness" 30 2
wait_for_url "https://creator.silvadigitaltech.com/login" "creator login" 30 2

ROLLBACK_NEEDED=0
trap - ERR
printf 'Deploy succeeded: %s (theme_updated=%s)\n' "$(git rev-parse HEAD)" "$theme_updated"
