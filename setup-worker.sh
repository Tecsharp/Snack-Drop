#!/usr/bin/env bash
# Conecta esta computadora a un servidor Snack-Drop como nodo ejecutor.
#   ./setup-worker.sh --server http://192.168.1.10:28743 --token sdn_xxx
#   ./setup-worker.sh --allow image.convert     limita las operaciones aceptadas
#   ./setup-worker.sh --down                    desconecta y detiene el nodo
set -euo pipefail
cd "$(dirname "$0")"

SERVER=""
TOKEN=""
ALLOW=""
ACTION="up"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server) SERVER="${2:?Falta la URL}"; shift 2 ;;
    --token) TOKEN="${2:?Falta el token}"; shift 2 ;;
    --allow) ALLOW="${2:?Faltan operaciones}"; shift 2 ;;
    --down) ACTION="down"; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; exit 1 ;;
  esac
done

fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker no está instalado. Alternativa sin Docker: ver README (python -m snackdrop_worker)."
docker info >/dev/null 2>&1 || fail "Docker no está en ejecución."
if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose); else COMPOSE=(docker-compose); fi
COMPOSE+=(-f docker-compose.worker.yml)

if [[ "$ACTION" == "down" ]]; then
  "${COMPOSE[@]}" down
  exit 0
fi

if [[ -z "$SERVER" ]]; then read -r -p "URL del servidor Snack-Drop (p. ej. http://192.168.1.10:28743): " SERVER; fi
if [[ -z "$TOKEN" ]]; then read -r -s -p "Token del nodo: " TOKEN; echo; fi
[[ "$SERVER" =~ ^https?:// ]] || fail "La URL debe empezar con http:// o https://"
[[ "$TOKEN" == sdn_* ]] || fail "El token debe empezar con sdn_"
SERVER="${SERVER%/}"

# Dentro del contenedor «localhost» es el propio contenedor.
if [[ "$SERVER" =~ ://(localhost|127\.0\.0\.1)(:|/|$) ]]; then
  SERVER="$(echo "$SERVER" | sed -E 's#://(localhost|127\.0\.0\.1)#://host.docker.internal#')"
  echo "ℹ Usando $SERVER para llegar al servidor desde el contenedor."
fi

umask 077
cat > worker.env <<EOF
SNACKDROP_SERVER=${SERVER}
SNACKDROP_TOKEN=${TOKEN}
SNACKDROP_NODE_HOSTNAME=$(hostname)
SNACKDROP_ALLOWED_OPERATIONS=${ALLOW}
EOF
chmod 600 worker.env

"${COMPOSE[@]}" up -d --build
echo
echo "✔ Nodo iniciado. Debería aparecer «en línea» en el panel en unos segundos."
echo "  Logs:     ${COMPOSE[*]} logs -f"
echo "  Detener:  ./setup-worker.sh --down"
