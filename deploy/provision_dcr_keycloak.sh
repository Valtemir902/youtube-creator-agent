#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${YCA_DEPLOY_DIR:-$HOME/apps/youtube-creator-agent}"
COMPOSE_FILE="deploy/docker-compose.oracle.yml"
DCR_CLIENT_ID="${YCA_DCR_PROVISIONER_CLIENT_ID:-yca-dcr-provisioner}"
TEMP_CLIENT_ID="yca-bootstrap-$(date +%s)-$$"
TEMP_SECRET="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
SECRET_OUT="${YCA_DCR_SECRET_OUT:-/tmp/yca-dcr-provisioner.secret}"

cd "$APP_DIR"
compose=(docker compose -f "$COMPOSE_FILE")
keycloak_started=0
temp_created=0
permanent_created=0

cleanup() {
  local code=$?
  trap - EXIT ERR INT TERM
  set +e
  if [[ "$keycloak_started" != "1" ]]; then
    "${compose[@]}" start keycloak >/dev/null 2>&1 || true
    keycloak_started=1
    sleep 2
  fi
  if [[ "$temp_created" == "1" ]]; then
    "${compose[@]}" exec -T \
      -e TEMP_ADMIN_ID="$TEMP_CLIENT_ID" \
      -e TEMP_ADMIN_SECRET="$TEMP_SECRET" \
      -e DCR_CLIENT_ID="$DCR_CLIENT_ID" \
      -e DELETE_DCR_CLIENT="$permanent_created" \
      keycloak sh -lc '
        set +e
        k=/opt/keycloak/bin/kcadm.sh
        "$k" config credentials --server http://localhost:8080 --realm master \
          --client "$TEMP_ADMIN_ID" --secret "$TEMP_ADMIN_SECRET" >/dev/null 2>&1 || exit 0
        if [ "$DELETE_DCR_CLIENT" = "1" ]; then
          did="$("$k" get clients -r yca -q clientId="$DCR_CLIENT_ID" | sed -n "s/.*\"id\" : \"\([^\"]*\)\".*/\1/p" | head -n1)"
          [ -z "$did" ] || "$k" delete clients/$did -r yca >/dev/null 2>&1 || true
        fi
        tid="$("$k" get clients -r master -q clientId="$TEMP_ADMIN_ID" | sed -n "s/.*\"id\" : \"\([^\"]*\)\".*/\1/p" | head -n1)"
        [ -z "$tid" ] || "$k" delete clients/$tid -r master >/dev/null 2>&1 || true
      ' >/dev/null 2>&1 || true
  fi
  rm -f "$SECRET_OUT"
  if (( code != 0 )); then
    echo "DCR provisioner bootstrap failed; temporary credentials were cleaned up." >&2
  fi
  exit "$code"
}
trap cleanup EXIT ERR INT TERM

rm -f "$SECRET_OUT"
umask 077

# Keycloak requires every node to be stopped before `bootstrap-admin` recovery.
"${compose[@]}" stop keycloak >/dev/null
keycloak_started=0

# Use the supported recovery command with the same production DB configuration
# inherited from the keycloak service. The secret is passed only via env.
"${compose[@]}" run --rm --no-deps \
  -e TEMP_BOOTSTRAP_CLIENT_ID="$TEMP_CLIENT_ID" \
  -e TEMP_BOOTSTRAP_CLIENT_SECRET="$TEMP_SECRET" \
  keycloak bootstrap-admin service \
    --client-id:env TEMP_BOOTSTRAP_CLIENT_ID \
    --client-secret:env TEMP_BOOTSTRAP_CLIENT_SECRET \
    --no-prompt >/dev/null

temp_created=1
"${compose[@]}" start keycloak >/dev/null
keycloak_started=1

# Wait until the temporary service account can authenticate.
ready=0
for _ in $(seq 1 45); do
  if "${compose[@]}" exec -T \
    -e TEMP_ADMIN_ID="$TEMP_CLIENT_ID" \
    -e TEMP_ADMIN_SECRET="$TEMP_SECRET" \
    keycloak sh -lc '
      /opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master \
        --client "$TEMP_ADMIN_ID" --secret "$TEMP_ADMIN_SECRET" >/dev/null 2>&1
    ' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" != "1" ]]; then
  echo "Keycloak did not become ready for temporary admin authentication." >&2
  exit 1
fi

# Reconcile the permanent least-privilege client, then print only its secret.
"${compose[@]}" exec -T \
  -e TEMP_ADMIN_ID="$TEMP_CLIENT_ID" \
  -e TEMP_ADMIN_SECRET="$TEMP_SECRET" \
  -e DCR_CLIENT_ID="$DCR_CLIENT_ID" \
  keycloak sh -lc '
    set -eu
    k=/opt/keycloak/bin/kcadm.sh
    "$k" config credentials --server http://localhost:8080 --realm master \
      --client "$TEMP_ADMIN_ID" --secret "$TEMP_ADMIN_SECRET" >/dev/null

    id="$("$k" get clients -r yca -q clientId="$DCR_CLIENT_ID" | sed -n "s/.*\"id\" : \"\([^\"]*\)\".*/\1/p" | head -n1)"
    created=0
    if [ -z "$id" ]; then
      "$k" create clients -r yca \
        -s clientId="$DCR_CLIENT_ID" \
        -s enabled=true \
        -s publicClient=false \
        -s serviceAccountsEnabled=true \
        -s standardFlowEnabled=false \
        -s directAccessGrantsEnabled=false \
        -s implicitFlowEnabled=false \
        -s fullScopeAllowed=true >/dev/null
      created=1
      id="$("$k" get clients -r yca -q clientId="$DCR_CLIENT_ID" | sed -n "s/.*\"id\" : \"\([^\"]*\)\".*/\1/p" | head -n1)"
    else
      "$k" update clients/$id -r yca \
        -s enabled=true \
        -s publicClient=false \
        -s serviceAccountsEnabled=true \
        -s standardFlowEnabled=false \
        -s directAccessGrantsEnabled=false \
        -s implicitFlowEnabled=false \
        -s fullScopeAllowed=true >/dev/null
    fi
    test -n "$id"

    uid="$("$k" get clients/$id/service-account-user -r yca | sed -n "s/.*\"id\" : \"\([^\"]*\)\".*/\1/p" | head -n1)"
    test -n "$uid"

    "$k" add-roles -r yca --uid "$uid" --cclientid realm-management --rolename manage-clients >/dev/null

    realm_roles="$("$k" get users/$uid/role-mappings/realm -r yca | sed -n "s/.*\"name\" : \"\([^\"]*\)\".*/\1/p")"
    for role in $realm_roles; do
      "$k" remove-roles -r yca --uid "$uid" --rolename "$role" >/dev/null || true
    done

    rm_id="$("$k" get clients -r yca -q clientId=realm-management | sed -n "s/.*\"id\" : \"\([^\"]*\)\".*/\1/p" | head -n1)"
    test -n "$rm_id"
    mapped="$("$k" get users/$uid/role-mappings/clients/$rm_id -r yca | sed -n "s/.*\"name\" : \"\([^\"]*\)\".*/\1/p")"
    for role in $mapped; do
      if [ "$role" != "manage-clients" ]; then
        "$k" remove-roles -r yca --uid "$uid" --cclientid realm-management --rolename "$role" >/dev/null || true
      fi
    done

    verify="$("$k" get users/$uid/role-mappings/clients/$rm_id -r yca | sed -n "s/.*\"name\" : \"\([^\"]*\)\".*/\1/p")"
    printf "%s\n" "$verify" | grep -qx manage-clients
    if printf "%s\n" "$verify" | grep -qx realm-admin; then
      echo "realm-admin is forbidden for DCR provisioner" >&2
      exit 1
    fi
    extras="$(printf "%s\n" "$verify" | sed "/^$/d;/^manage-clients$/d")"
    test -z "$extras"

    echo "created=$created" >&2
    "$k" get clients/$id/client-secret -r yca | sed -n "s/.*\"value\" : \"\([^\"]*\)\".*/\1/p" | head -n1
  ' > "$SECRET_OUT" 2>/tmp/yca-dcr-provisioner-status

if grep -q '^created=1$' /tmp/yca-dcr-provisioner-status; then
  permanent_created=1
fi
rm -f /tmp/yca-dcr-provisioner-status

test -s "$SECRET_OUT"
chmod 600 "$SECRET_OUT"

dcr_secret="$(tr -d '\r\n' < "$SECRET_OUT")"
"${compose[@]}" exec -T \
  -e DCR_CLIENT_ID="$DCR_CLIENT_ID" \
  -e DCR_CLIENT_SECRET="$dcr_secret" \
  onboarding python - <<'PY'
import json, os, urllib.parse, urllib.request
body = urllib.parse.urlencode({
    "grant_type": "client_credentials",
    "client_id": os.environ["DCR_CLIENT_ID"],
    "client_secret": os.environ["DCR_CLIENT_SECRET"],
}).encode("ascii")
req = urllib.request.Request(
    "http://keycloak:8080/realms/yca/protocol/openid-connect/token",
    data=body,
    headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
)
with urllib.request.urlopen(req, timeout=8) as response:
    payload = json.loads(response.read().decode("utf-8"))
    assert response.status == 200
    assert isinstance(payload.get("access_token"), str) and payload["access_token"]
print("dcr_provisioner_client_credentials=ok")
PY

"${compose[@]}" exec -T \
  -e TEMP_ADMIN_ID="$TEMP_CLIENT_ID" \
  -e TEMP_ADMIN_SECRET="$TEMP_SECRET" \
  keycloak sh -lc '
    set -eu
    k=/opt/keycloak/bin/kcadm.sh
    "$k" config credentials --server http://localhost:8080 --realm master \
      --client "$TEMP_ADMIN_ID" --secret "$TEMP_ADMIN_SECRET" >/dev/null
    tid="$("$k" get clients -r master -q clientId="$TEMP_ADMIN_ID" | sed -n "s/.*\"id\" : \"\([^\"]*\)\".*/\1/p" | head -n1)"
    test -n "$tid"
    "$k" delete clients/$tid -r master >/dev/null
  '

temp_created=0
permanent_created=0
trap - EXIT ERR INT TERM
printf 'dcr_provisioner_ready\n'
