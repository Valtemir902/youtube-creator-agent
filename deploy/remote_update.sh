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

echo "Deploying commit $TARGET_SHA (previous: $PREVIOUS_SHA)"
git fetch --prune origin "$TARGET_SHA"
git checkout feat/web-dashboard-v1
git reset --hard "$TARGET_SHA"

if [[ ! -f config/server.env ]]; then
  echo "Missing config/server.env on VPS" >&2
  exit 4
fi

if grep -q '^YCA_WEB_OIDC_BACKCHANNEL_BASE_URL=' config/server.env; then
  sed -i "s#^YCA_WEB_OIDC_BACKCHANNEL_BASE_URL=.*#YCA_WEB_OIDC_BACKCHANNEL_BASE_URL=$BACKCHANNEL_VALUE#" config/server.env
else
  printf '\nYCA_WEB_OIDC_BACKCHANNEL_BASE_URL=%s\n' "$BACKCHANNEL_VALUE" >> config/server.env
fi

# Build only application services. Keycloak/Postgres/Cloudflared remain untouched here.
docker compose -f "$COMPOSE_FILE" up -d --build mcp onboarding

docker compose -f "$COMPOSE_FILE" ps mcp onboarding keycloak

# Internal identity-provider backchannel must be reachable from onboarding.
docker compose -f "$COMPOSE_FILE" exec -T onboarding \
  python -c "import urllib.request; r=urllib.request.urlopen('http://keycloak:8080/realms/yca/.well-known/openid-configuration', timeout=8); print('keycloak_backchannel', r.status); assert r.status == 200"

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

  # Realm theme changes are stored in the database and are normally picked up
  # without a full Keycloak restart. Verify the public identity provider instead
  # of deliberately creating an authentication outage.
  wait_for_url "https://auth.silvadigitaltech.com/realms/yca/.well-known/openid-configuration" "public keycloak after theme update" 30 2
fi

# All public surfaces must be healthy before considering the deployment complete.
wait_for_url "https://auth.silvadigitaltech.com/realms/yca/.well-known/openid-configuration" "public keycloak" 30 2
wait_for_url "https://creator.silvadigitaltech.com/health" "creator health" 30 2
wait_for_url "https://creator.silvadigitaltech.com/ready" "creator readiness" 30 2
wait_for_url "https://creator.silvadigitaltech.com/login" "creator login" 30 2

ROLLBACK_NEEDED=0
trap - ERR
printf 'Deploy succeeded: %s (theme_updated=%s)\n' "$(git rev-parse HEAD)" "$theme_updated"
