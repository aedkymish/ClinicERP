#!/usr/bin/env bash
# ClinicERP v2 - server installer for Linux / macOS (Docker).
#
# Safe to run again: it keeps existing secrets, certificates and data, rebuilds the
# containers and only creates an administrator when none exists yet.
#
# Usage: ./install.sh [options]
#   --domain NAME        Host name for the self-signed certificate (default: this machine's name)
#   --admin NAME         Username of the first administrator (default: admin)
#   --http-port N        HTTP port, redirects to HTTPS (default: 80)
#   --https-port N       HTTPS port (default: 443)
#   --offsite PATH       Folder for off-server backup copies, e.g. a mounted NAS (default: ./offsite-backups)
#   --cert FILE --key FILE   Use your own TLS certificate instead of a self-signed one
#   -h, --help           Show this help
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"

DOMAIN="$(hostname 2>/dev/null || echo localhost)"
ADMIN="admin"
HTTP_PORT=""
HTTPS_PORT=""
OFFSITE=""
CERT=""
KEY=""

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m OK\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m !!\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --domain)     DOMAIN="${2:?}"; shift 2 ;;
    --admin)      ADMIN="${2:?}"; shift 2 ;;
    --http-port)  HTTP_PORT="${2:?}"; shift 2 ;;
    --https-port) HTTPS_PORT="${2:?}"; shift 2 ;;
    --offsite)    OFFSITE="${2:?}"; shift 2 ;;
    --cert)       CERT="${2:?}"; shift 2 ;;
    --key)        KEY="${2:?}"; shift 2 ;;
    -h|--help)    usage ;;
    *) die "Unknown option: $1 (see --help)" ;;
  esac
done

# ------------------------------------------------------------------ prerequisites
info "Checking Docker"
command -v docker >/dev/null 2>&1 || die "Docker is not installed. Install Docker Engine (Linux) or Docker Desktop (macOS) first: https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 || die "Docker is installed but not running, or this user cannot use it. Start Docker (or add your user to the 'docker' group / run with sudo) and try again."
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  die "Docker Compose is not available. Install the Docker Compose plugin: https://docs.docker.com/compose/install/"
fi
ok "$(docker --version)"

# ------------------------------------------------------------------ helpers
random_token() {  # URL-safe random string
  if command -v openssl >/dev/null 2>&1; then openssl rand -base64 48 | tr -d '\n=+/' | cut -c1-64
  else head -c 48 /dev/urandom | base64 | tr -d '\n=+/' | cut -c1-64; fi
}
fernet_key() {    # 32 random bytes, URL-safe base64 (44 chars) - the format Fernet expects
  head -c 32 /dev/urandom | base64 | tr -d '\n' | tr '+/' '-_'
}
env_get() { [ -f "$1" ] && grep -E "^$2=" "$1" | tail -1 | cut -d= -f2- || true; }
env_set() {       # env_set FILE KEY VALUE  (replace or append)
  local file="$1" key="$2" value="$3" tmp
  touch "$file"
  tmp="$(mktemp)"
  grep -vE "^$key=" "$file" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  cat "$tmp" > "$file"; rm -f "$tmp"
}

# ------------------------------------------------------------------ settings
info "Preparing configuration"
API_ENV="backend/.env"
ROOT_ENV=".env"
if [ ! -f "$API_ENV" ]; then
  cp backend/.env.example "$API_ENV"
  ok "Created $API_ENV"
fi
[ -n "$(env_get "$API_ENV" CLINIC_SECRET_KEY)" ] && [ "$(env_get "$API_ENV" CLINIC_SECRET_KEY | cut -c1-8)" != "generate" ] \
  || { env_set "$API_ENV" CLINIC_SECRET_KEY "$(random_token)"; ok "Generated a new session signing key"; }
[ -n "$(env_get "$API_ENV" CLINIC_BACKUP_ENCRYPTION_KEY)" ] \
  || { env_set "$API_ENV" CLINIC_BACKUP_ENCRYPTION_KEY "$(fernet_key)"; ok "Generated a backup encryption key"; }
env_set "$API_ENV" CLINIC_COOKIE_SECURE true
chmod 600 "$API_ENV"

# ports and off-site folder live in the root .env that docker compose reads
HTTP_PORT="${HTTP_PORT:-$(env_get "$ROOT_ENV" HTTP_PORT)}";   HTTP_PORT="${HTTP_PORT:-80}"
HTTPS_PORT="${HTTPS_PORT:-$(env_get "$ROOT_ENV" HTTPS_PORT)}"; HTTPS_PORT="${HTTPS_PORT:-443}"
OFFSITE="${OFFSITE:-$(env_get "$ROOT_ENV" OFFSITE_BACKUP_PATH)}"; OFFSITE="${OFFSITE:-./offsite-backups}"
env_set "$ROOT_ENV" COMPOSE_PROJECT_NAME clinicerp
env_set "$ROOT_ENV" HTTP_PORT "$HTTP_PORT"
env_set "$ROOT_ENV" HTTPS_PORT "$HTTPS_PORT"
env_set "$ROOT_ENV" OFFSITE_BACKUP_PATH "$OFFSITE"

mkdir -p "$OFFSITE"
chmod 0777 "$OFFSITE" 2>/dev/null || warn "Could not make $OFFSITE writable; off-server backup copies may fail"
ok "Ports: HTTP $HTTP_PORT, HTTPS $HTTPS_PORT. Off-server backups: $OFFSITE"

# ------------------------------------------------------------------ TLS certificate
info "Preparing the TLS certificate"
mkdir -p deploy/certs
if [ -n "$CERT" ] || [ -n "$KEY" ]; then
  [ -f "$CERT" ] && [ -f "$KEY" ] || die "--cert and --key must both point to existing files"
  cp "$CERT" deploy/certs/fullchain.pem
  cp "$KEY" deploy/certs/privkey.pem
  ok "Installed your certificate"
elif [ -f deploy/certs/fullchain.pem ] && [ -f deploy/certs/privkey.pem ]; then
  ok "Keeping the existing certificate in deploy/certs"
else
  SUBJ="/CN=$DOMAIN"
  SAN="subjectAltName=DNS:$DOMAIN,DNS:localhost,IP:127.0.0.1"
  if command -v openssl >/dev/null 2>&1; then
    openssl req -x509 -nodes -newkey rsa:2048 -days 825 -subj "$SUBJ" -addext "$SAN" \
      -keyout deploy/certs/privkey.pem -out deploy/certs/fullchain.pem >/dev/null 2>&1
  else
    docker run --rm -v "$ROOT/deploy/certs:/certs" alpine/openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
      -subj "$SUBJ" -addext "$SAN" -keyout /certs/privkey.pem -out /certs/fullchain.pem >/dev/null 2>&1
  fi
  chmod 644 deploy/certs/fullchain.pem; chmod 600 deploy/certs/privkey.pem
  ok "Created a self-signed certificate for $DOMAIN (browsers will warn until you install a real one)"
fi

# ------------------------------------------------------------------ build and start
info "Building and starting the containers (the first build can take several minutes)"
if ! "${COMPOSE[@]}" up -d --build; then
  warn "Build failed - retrying once (slow networks often time out on the first try)"
  "${COMPOSE[@]}" up -d --build || die "docker compose failed. See the messages above."
fi

info "Waiting for the API to become ready"
for i in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" >/dev/null 2>&1; then
    ok "API is up"; break
  fi
  [ "$i" -eq 60 ] && { "${COMPOSE[@]}" logs --tail 50 api; die "The API did not start. See the log above."; }
  sleep 2
done

# ------------------------------------------------------------------ first administrator
ADMINS="$("${COMPOSE[@]}" exec -T api python -m app.cli admin-count 2>/dev/null | tr -dc '0-9')"
if [ "${ADMINS:-0}" = "0" ]; then
  info "Creating the first administrator '$ADMIN'"
  "${COMPOSE[@]}" exec -T api python -m app.cli create-admin "$ADMIN"
  warn "Write the one-time password down now; it is shown only once."
else
  ok "An administrator already exists; no account was created"
fi

# ------------------------------------------------------------------ done
PORT_SUFFIX=""; [ "$HTTPS_PORT" != "443" ] && PORT_SUFFIX=":$HTTPS_PORT"
echo
ok "ClinicERP is running: https://$DOMAIN$PORT_SUFFIX"
cat <<EOF

  Useful commands (run in $ROOT):
    ${COMPOSE[*]} ps                  # container status
    ${COMPOSE[*]} logs -f             # follow logs
    ${COMPOSE[*]} exec api python -m app.cli backup     # backup now
    ${COMPOSE[*]} down                # stop (data is kept in the 'clinic-data' volume)
    ./install.sh                      # update after pulling new code

  Keep a copy of backend/.env somewhere safe: without CLINIC_BACKUP_ENCRYPTION_KEY
  the encrypted backups cannot be restored.
EOF
