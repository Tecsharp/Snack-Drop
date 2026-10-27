#!/usr/bin/env bash
# Instala e inicia Snack-Drop con un solo comando.
#   ./setup.sh                      instalación interactiva
#   ./setup.sh --port 9000          puerto HTTP distinto (por defecto 8080)
#   ./setup.sh --deepseek-key sk-…  activa el asistente DeepSeek
#   ./setup.sh --yes                sin preguntas (usa valores por defecto)
#   ./setup.sh --down               detiene los contenedores
set -euo pipefail
cd "$(dirname "$0")"

PORT=""
DEEPSEEK_KEY=""
ASSUME_YES=0
ACTION="up"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="${2:?Falta el puerto}"; shift 2 ;;
    --deepseek-key) DEEPSEEK_KEY="${2:?Falta la API key}"; shift 2 ;;
    -y|--yes) ASSUME_YES=1; shift ;;
    --down) ACTION="down"; shift ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; exit 1 ;;
  esac
done

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '\033[35m▸\033[0m %s\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker no está instalado. Instálalo desde https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 || fail "Docker no está en ejecución (o tu usuario no tiene permiso para usarlo)."
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  fail "Falta Docker Compose v2 (docker compose)."
fi

if [[ "$ACTION" == "down" ]]; then
  "${COMPOSE[@]}" down
  exit 0
fi

random() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c "$1" || true; }

strong_password() {
  local p
  while :; do
    p="$(random 20)"
    [[ "$p" =~ [a-z] && "$p" =~ [A-Z] && "$p" =~ [0-9] ]] && { echo "$p"; return; }
  done
}

ask() { # ask "pregunta" "valor por defecto"
  local answer
  if [[ $ASSUME_YES -eq 1 || ! -t 0 ]]; then echo "$2"; return; fi
  read -r -p "$1 [$2]: " answer
  echo "${answer:-$2}"
}

env_get() { grep -E "^$1=" .env 2>/dev/null | head -n1 | cut -d= -f2- || true; }

env_set() { # env_set CLAVE valor  (reemplaza o agrega)
  local tmp
  tmp="$(mktemp)"
  grep -vE "^$1=" .env > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  mv "$tmp" .env
  chmod 600 .env
}

bold "Snack-Drop · instalación"
FIRST_RUN=0
if [[ ! -f .env ]]; then
  FIRST_RUN=1
  PORT="${PORT:-$(ask "Puerto HTTP" "8080")}"
  if [[ -z "$DEEPSEEK_KEY" && $ASSUME_YES -eq 0 && -t 0 ]]; then
    read -r -s -p "API key de DeepSeek (opcional, Enter para omitir): " DEEPSEEK_KEY || true
    echo
  fi
  ADMIN_PASSWORD="$(strong_password)"
  umask 077
  cat > .env <<EOF
# Generado por setup.sh el $(date -u +%Y-%m-%dT%H:%M:%SZ). No lo subas a git.
SNACKDROP_HTTP_PORT=${PORT}
SNACKDROP_SECRET_KEY=$(random 64)
SNACKDROP_ADMIN_USERNAME=admin
# Solo se usa al crear la base de datos por primera vez.
SNACKDROP_ADMIN_PASSWORD=${ADMIN_PASSWORD}
SNACKDROP_LOCAL_NODE_TOKEN=sdn_$(random 43)
SNACKDROP_LOCAL_NODE_NAME=master
# Pon true si sirves Snack-Drop detrás de HTTPS.
SNACKDROP_COOKIE_SECURE=false
SNACKDROP_SESSION_TTL_MINUTES=720
SNACKDROP_MAX_UPLOAD_MB=2048
SNACKDROP_MAX_FILES_PER_JOB=500
DEEPSEEK_API_KEY=${DEEPSEEK_KEY}
DEEPSEEK_MODEL=deepseek-chat
EOF
  chmod 600 .env
  info "Archivo .env creado con secretos aleatorios."
else
  info "Usando .env existente."
  [[ -n "$PORT" ]] && env_set SNACKDROP_HTTP_PORT "$PORT"
  [[ -n "$DEEPSEEK_KEY" ]] && env_set DEEPSEEK_API_KEY "$DEEPSEEK_KEY"
  PORT="$(env_get SNACKDROP_HTTP_PORT)"
  PORT="${PORT:-8080}"
fi

info "Construyendo e iniciando contenedores (la primera vez tarda unos minutos)…"
"${COMPOSE[@]}" up -d --build

info "Esperando a que el servidor responda…"
URL="http://localhost:${PORT}"
for _ in $(seq 1 90); do
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$URL/api/health" >/dev/null 2>&1 && break
  else
    "${COMPOSE[@]}" ps backend 2>/dev/null | grep -q healthy && break
  fi
  sleep 2
done

LAN_IP="$( (hostname -I 2>/dev/null | awk '{print $1}') || true)"
if [[ -z "$LAN_IP" ]] && command -v ipconfig >/dev/null 2>&1; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
fi

echo
bold "✔ Snack-Drop está listo"
echo "  Abre:        $URL"
[[ -n "$LAN_IP" ]] && echo "  En tu red:   http://${LAN_IP}:${PORT}"
echo "  Usuario:     admin"
if [[ $FIRST_RUN -eq 1 ]]; then
  echo "  Contraseña:  ${ADMIN_PASSWORD}"
  echo
  echo "  Guarda la contraseña ahora y cámbiala en «Cuenta». También quedó en .env (SNACKDROP_ADMIN_PASSWORD),"
  echo "  pero solo se usa en la primera instalación."
else
  echo "  Contraseña:  la definida en la primera instalación."
fi
echo
echo "  Para sumar otra computadora: crea un nodo en «Nodos» y ejecuta allí ./setup-worker.sh"
echo "  Detener:     ./setup.sh --down"
