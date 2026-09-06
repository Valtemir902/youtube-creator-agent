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
  if [[ "$ROLLBACK_NEEDED" == "1" ]]; then
    echo "Deploy failed with exit code $code. Rolling back to $PREVIOUS_SHA" >&2
    git reset --hard "$PREVIOUS_SHA" || true
    docker compose -f "$COMPOSE_FILE" up -d --build mcp onboarding || true
  fi
  exit "$code"
}
trap rollback ERR

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

# Build only application services. Keycloak/Postgres/Cloudflared remain untouched.
docker compose -f "$COMPOSE_FILE" up -d --build mcp onboarding

docker compose -f "$COMPOSE_FILE" ps mcp onboarding keycloak

# Internal identity-provider backchannel must be reachable from onboarding.
docker compose -f "$COMPOSE_FILE" exec -T onboarding \
  python -c "import urllib.request; r=urllib.request.urlopen('http://keycloak:8080/realms/yca/.well-known/openid-configuration', timeout=8); print('keycloak_backchannel', r.status); assert r.status == 200"

# Public probes prove the tunnel and application are serving again.
curl --fail --show-error --silent --location --max-time 20 https://creator.silvadigitaltech.com/health >/dev/null
curl --fail --show-error --silent --location --max-time 20 https://creator.silvadigitaltech.com/ready >/dev/null

ROLLBACK_NEEDED=0
trap - ERR

echo "Deploy succeeded: $(git rev-parse HEAD)"
