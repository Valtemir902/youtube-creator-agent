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
INTROSPECTION_BACKCHANNEL_VALUE="http://keycloak:8080/realms/yca/protocol/openid-connect/token/introspect"
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
    echo "Deploy failed with exit code $code. Rolling back to $PREVIOUS_SHA" >&2
    git reset --hard "$PREVIOUS_SHA" || true
    docker compose -f "$COMPOSE_FILE" up -d --build mcp onboarding || true
  fi
  exit "$code"
}
trap rollback ERR

wait_for_url() {
  local url="$1"
  local label="$2"
  local attempts="${3:-30}"
  local delay="${4:-2}"
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
  local key="$1"
  local value="$2"
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

# Browser-facing OIDC remains public, while server-to-server calls stay on the
# Docker network. Sending introspection through Cloudflare caused Error 1010.
set_env_value YCA_WEB_OIDC_BACKCHANNEL_BASE_URL "$BACKCHANNEL_VALUE"
set_env_value YCA_AUTH_INTROSPECTION_URL "$INTROSPECTION_BACKCHANNEL_VALUE"

# Repair the fixed ChatGPT OAuth client's custom scopes idempotently. The
# bootstrap admin account may be stale, so this narrowly-scoped migration uses
# the Keycloak database and restarts Keycloak only when rows actually change.
chatgpt_client_id="$(grep -E '^YCA_CHATGPT_OAUTH_CLIENT_ID=' config/server.env | tail -n1 | cut -d= -f2- | tr -d '\r')"
if [[ -z "$chatgpt_client_id" ]]; then
  echo "YCA_CHATGPT_OAUTH_CLIENT_ID is required for OAuth repair" >&2
  exit 5
fi

scope_migration="$({ docker compose -f "$COMPOSE_FILE" exec -T -e CHATGPT_CLIENT_ID="$chatgpt_client_id" keycloak-db sh -lc 'set -eu; psql -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
WITH realm_row AS (
  SELECT id FROM realm WHERE name='yca'
), inserted_read AS (
  INSERT INTO client_scope (id, name, realm_id, description, protocol)
  SELECT md5(random()::text || clock_timestamp()::text), 'yca:read', id,
         'Read access to the authenticated YouTube Creator Agent tenant', 'openid-connect'
  FROM realm_row
  WHERE NOT EXISTS (
    SELECT 1 FROM client_scope cs JOIN realm r ON r.id=cs.realm_id
    WHERE r.name='yca' AND cs.name='yca:read'
  )
  RETURNING 1
), inserted_write AS (
  INSERT INTO client_scope (id, name, realm_id, description, protocol)
  SELECT md5(random()::text || clock_timestamp()::text), 'yca:write', id,
         'Write access to explicitly approved YouTube Creator Agent actions', 'openid-connect'
  FROM realm_row
  WHERE NOT EXISTS (
    SELECT 1 FROM client_scope cs JOIN realm r ON r.id=cs.realm_id
    WHERE r.name='yca' AND cs.name='yca:write'
  )
  RETURNING 1
), inserted_read_assignment AS (
  INSERT INTO client_scope_client (client_id, scope_id, default_scope)
  SELECT c.id, cs.id, TRUE
  FROM client c
  JOIN realm r ON r.id=c.realm_id
  JOIN client_scope cs ON cs.realm_id=r.id AND cs.name='yca:read'
  WHERE r.name='yca' AND c.client_id=current_setting('CHATGPT_CLIENT_ID', true)
    AND NOT EXISTS (
      SELECT 1 FROM client_scope_client x WHERE x.client_id=c.id AND x.scope_id=cs.id
    )
  RETURNING 1
), inserted_write_assignment AS (
  INSERT INTO client_scope_client (client_id, scope_id, default_scope)
  SELECT c.id, cs.id, FALSE
  FROM client c
  JOIN realm r ON r.id=c.realm_id
  JOIN client_scope cs ON cs.realm_id=r.id AND cs.name='yca:write'
  WHERE r.name='yca' AND c.client_id=current_setting('CHATGPT_CLIENT_ID', true)
    AND NOT EXISTS (
      SELECT 1 FROM client_scope_client x WHERE x.client_id=c.id AND x.scope_id=cs.id
    )
  RETURNING 1
)
SELECT
  (SELECT count(*) FROM inserted_read) +
  (SELECT count(*) FROM inserted_write) +
  (SELECT count(*) FROM inserted_read_assignment) +
  (SELECT count(*) FROM inserted_write_assignment);
SQL
} )"

# PostgreSQL custom settings are not automatically inherited from shell env.
# If the first migration could not resolve the client via current_setting, apply
# the assignment with psql variables while preserving the already-created scopes.
if [[ ! "$scope_migration" =~ ^[0-9]+$ ]]; then
  echo "Unexpected OAuth scope migration result: $scope_migration" >&2
  exit 6
fi

# Ensure assignments exist using a quoted psql variable. This is idempotent and
# does not expose the client identifier in logs.
assignment_migration="$({ docker compose -f "$COMPOSE_FILE" exec -T -e CHATGPT_CLIENT_ID="$chatgpt_client_id" keycloak-db sh -lc 'set -eu; psql -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v chatgpt_client_id="$CHATGPT_CLIENT_ID"' <<'SQL'
WITH target AS (
  SELECT c.id AS client_pk, r.id AS realm_pk
  FROM client c JOIN realm r ON r.id=c.realm_id
  WHERE r.name='yca' AND c.client_id=:'chatgpt_client_id'
), read_add AS (
  INSERT INTO client_scope_client (client_id, scope_id, default_scope)
  SELECT t.client_pk, cs.id, TRUE
  FROM target t JOIN client_scope cs ON cs.realm_id=t.realm_pk AND cs.name='yca:read'
  WHERE NOT EXISTS (SELECT 1 FROM client_scope_client x WHERE x.client_id=t.client_pk AND x.scope_id=cs.id)
  RETURNING 1
), write_add AS (
  INSERT INTO client_scope_client (client_id, scope_id, default_scope)
  SELECT t.client_pk, cs.id, FALSE
  FROM target t JOIN client_scope cs ON cs.realm_id=t.realm_pk AND cs.name='yca:write'
  WHERE NOT EXISTS (SELECT 1 FROM client_scope_client x WHERE x.client_id=t.client_pk AND x.scope_id=cs.id)
  RETURNING 1
)
SELECT (SELECT count(*) FROM target), (SELECT count(*) FROM read_add) + (SELECT count(*) FROM write_add);
SQL
} )"

if [[ ! "$assignment_migration" =~ ^1\|[0-9]+$ ]]; then
  echo "Fixed ChatGPT OAuth client was not found or scope assignment failed" >&2
  exit 7
fi

scope_changes="${scope_migration}"
assignment_changes="${assignment_migration#*|}"
if (( scope_changes > 0 || assignment_changes > 0 )); then
  echo "OAuth client scopes repaired; restarting Keycloak to invalidate cached realm/client metadata"
  docker compose -f "$COMPOSE_FILE" restart keycloak
  wait_for_url "https://auth.silvadigitaltech.com/realms/yca/.well-known/openid-configuration" "public keycloak after OAuth scope repair" 45 2
else
  echo "OAuth client scopes already configured"
fi

# Build only application services. Postgres/Cloudflared remain untouched here.
docker compose -f "$COMPOSE_FILE" up -d --build mcp onboarding

docker compose -f "$COMPOSE_FILE" ps mcp onboarding keycloak

# Internal identity-provider backchannel must be reachable from onboarding.
docker compose -f "$COMPOSE_FILE" exec -T onboarding \
  python -c "import urllib.request; r=urllib.request.urlopen('http://keycloak:8080/realms/yca/.well-known/openid-configuration', timeout=8); print('keycloak_backchannel', r.status); assert r.status == 200"

# MCP introspection must never hairpin through Cloudflare. An invalid token should
# still produce a valid RFC 7662 response with active=false.
docker compose -f "$COMPOSE_FILE" exec -T mcp python - <<'PY'
import base64, json, os, urllib.parse, urllib.request
endpoint=os.environ['YCA_AUTH_INTROSPECTION_URL']
assert endpoint.startswith('http://keycloak:8080/'), endpoint
client_id=os.environ['YCA_AUTH_INTROSPECTION_CLIENT_ID']
secret=os.environ['YCA_AUTH_INTROSPECTION_CLIENT_SECRET']
body=urllib.parse.urlencode({'token':'deployment-smoke-invalid-token'}).encode('ascii')
basic=base64.b64encode(f'{client_id}:{secret}'.encode()).decode('ascii')
req=urllib.request.Request(endpoint,data=body,method='POST',headers={'Authorization':f'Basic {basic}','Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'})
with urllib.request.urlopen(req,timeout=8) as response:
    payload=json.loads(response.read().decode())
    assert response.status == 200
    assert payload.get('active') is False, payload
print('mcp_introspection_backchannel ok')
PY

# Verify both custom scopes are recognized by the fixed public client. No user
# credentials are involved; a valid authorization request must render login,
# not bounce invalid_scope back to ChatGPT.
docker compose -f "$COMPOSE_FILE" exec -T onboarding python - <<'PY'
import base64, hashlib, os, secrets, urllib.parse, urllib.request
client_id=os.environ['YCA_CHATGPT_OAUTH_CLIENT_ID']
verifier=secrets.token_urlsafe(48)
challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
params={
    'response_type':'code',
    'client_id':client_id,
    'redirect_uri':'https://chatgpt.com/connector_platform_oauth_redirect',
    'scope':'openid email offline_access yca:read yca:write',
    'state':'deploy-smoke',
    'code_challenge':challenge,
    'code_challenge_method':'S256',
}
url='http://keycloak:8080/realms/yca/protocol/openid-connect/auth?'+urllib.parse.urlencode(params)
req=urllib.request.Request(url,headers={'Host':'auth.silvadigitaltech.com','X-Forwarded-Proto':'https'})
with urllib.request.urlopen(req,timeout=8) as response:
    body=response.read(4096).decode('utf-8','replace').lower()
    assert response.status == 200
    assert 'invalid_scope' not in body
print('keycloak_custom_scopes ok')
PY

# Do not touch or restart Keycloak on every application deploy. First inspect the
# current realm theme directly. Only attempt a mutation when the configured theme
# actually differs from the desired value.
theme_updated=0
current_theme="$({ docker compose -f "$COMPOSE_FILE" exec -T keycloak-db sh -lc 'set -eu; psql -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT COALESCE(login_theme, '') FROM realm WHERE name='yca';
SQL
} | tr -d '\r' | tail -n 1)"

if [[ "$current_theme" == "$DESIRED_LOGIN_THEME" ]]; then
  echo "keycloak login theme already configured: $DESIRED_LOGIN_THEME"
else
  echo "keycloak login theme differs (${current_theme:-<empty>}); updating to $DESIRED_LOGIN_THEME"
  if docker compose -f "$COMPOSE_FILE" exec -T keycloak sh -lc '
    set -eu
    admin_user="${KC_BOOTSTRAP_ADMIN_USERNAME:-}"
    admin_pass="${KC_BOOTSTRAP_ADMIN_PASSWORD:-}"
    test -n "$admin_user" && test -n "$admin_pass"
    cfg=/tmp/kcadm-yca-deploy.config
    rm -f "$cfg"
    /opt/keycloak/bin/kcadm.sh config credentials --config "$cfg" --server http://127.0.0.1:8080 --realm master --user "$admin_user" --password "$admin_pass" >/dev/null
    /opt/keycloak/bin/kcadm.sh update realms/yca --config "$cfg" -s loginTheme=keycloak.v2 >/dev/null
    rm -f "$cfg"
  '; then
    theme_updated=1
    echo "keycloak login theme set via Admin API: $DESIRED_LOGIN_THEME"
  else
    echo "Keycloak bootstrap-admin login is stale; applying scoped realm-theme DB fallback" >&2
    set +e
    db_result="$({ docker compose -f "$COMPOSE_FILE" exec -T keycloak-db sh -lc 'set -eu; psql -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
UPDATE realm SET login_theme='keycloak.v2' WHERE name='yca' AND login_theme IS DISTINCT FROM 'keycloak.v2';
SELECT COALESCE(login_theme, '') FROM realm WHERE name='yca';
SQL
    } 2>&1)"
    db_code=$?
    set -e
    if [[ "$db_code" == "0" && "${db_result##*$'\n'}" == "$DESIRED_LOGIN_THEME" ]]; then
      theme_updated=1
      echo "keycloak login theme set via scoped DB fallback: $DESIRED_LOGIN_THEME"
    else
      echo "WARNING: could not enforce $DESIRED_LOGIN_THEME login theme; application deploy will continue" >&2
      printf '%s\n' "$db_result" >&2
    fi
  fi

  wait_for_url "https://auth.silvadigitaltech.com/realms/yca/.well-known/openid-configuration" "public keycloak after theme update" 30 2
fi

wait_for_url "https://auth.silvadigitaltech.com/realms/yca/.well-known/openid-configuration" "public keycloak" 30 2
wait_for_url "https://creator.silvadigitaltech.com/health" "creator health" 30 2
wait_for_url "https://creator.silvadigitaltech.com/ready" "creator readiness" 30 2
wait_for_url "https://creator.silvadigitaltech.com/login" "creator login" 30 2

ROLLBACK_NEEDED=0
trap - ERR
printf 'Deploy succeeded: %s (theme_updated=%s)\n' "$(git rev-parse HEAD)" "$theme_updated"
