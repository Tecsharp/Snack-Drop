#!/usr/bin/env bash
# Conecta esta computadora a un servidor Snack-Drop como nodo ejecutor.
#   ./setup-worker.sh --server http://192.168.1.10:28743 --token sdn_xxx
#   ./setup-worker.sh                           reconstruye usando el worker.env existente
#   ./setup-worker.sh --with-office             agrega LibreOffice (Word/Excel/PowerPoint → PDF, +~600 MB)
#   ./setup-worker.sh --with-ai                 agrega IA: quitar fondo, ampliar, transcribir (+~1.5 GB)
#   ./setup-worker.sh --allow image.convert     limita las operaciones aceptadas
#   ./setup-worker.sh --down                    desconecta y detiene el nodo
set -euo pipefail
cd "$(dirname "$0")"

SERVER=""
TOKEN=""
ALLOW=""
ALLOW_SET=0
WITH_OFFICE=""
WITH_AI=""
ACTION="up"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server) SERVER="${2:?Falta la URL}"; shift 2 ;;
    --token) TOKEN="${2:?Falta el token}"; shift 2 ;;
    --allow) ALLOW="${2:?Faltan operaciones}"; ALLOW_SET=1; shift 2 ;;
    --with-office) WITH_OFFICE=true; shift ;;
    --without-office) WITH_OFFICE=false; shift ;;
    --with-ai) WITH_AI=true; shift ;;
    --without-ai) WITH_AI=false; shift ;;
    --down) ACTION="down"; shift ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; exit 1 ;;
  esac
done

fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker no está instalado. Alternativa sin Docker: ver README (python -m snackdrop_worker)."
docker info >/dev/null 2>&1 || fail "Docker no está en ejecución."
if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose); else COMPOSE=(docker-compose); fi
COMPOSE+=(-f docker-compose.worker.yml --env-file worker.env)

if [[ "$ACTION" == "down" ]]; then
  [[ -f worker.env ]] || touch worker.env
  "${COMPOSE[@]}" down
  exit 0
fi

current() { grep -E "^$1=" worker.env 2>/dev/null | head -n1 | cut -d= -f2- || true; }

if [[ -f worker.env && -z "$SERVER" && -z "$TOKEN" ]]; then
  SERVER="$(current SNACKDROP_SERVER)"
  TOKEN="$(current SNACKDROP_TOKEN)"
  echo "ℹ Usando la configuración existente de worker.env ($SERVER)."
fi
[[ $ALLOW_SET -eq 1 ]] || ALLOW="$(current SNACKDROP_ALLOWED_OPERATIONS)"
WITH_OFFICE="${WITH_OFFICE:-$(current SNACKDROP_WORKER_OFFICE)}"
WITH_AI="${WITH_AI:-$(current SNACKDROP_WORKER_AI)}"

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
SNACKDROP_WORKER_OFFICE=${WITH_OFFICE:-false}
SNACKDROP_WORKER_AI=${WITH_AI:-false}
EOF
chmod 600 worker.env

[[ "${WITH_OFFICE:-false}" == "true" ]] && echo "ℹ Incluyendo LibreOffice (Office → PDF)."
[[ "${WITH_AI:-false}" == "true" ]] && echo "ℹ Incluyendo IA (la primera construcción descarga ~1.5 GB)."

"${COMPOSE[@]}" up -d --build
echo
echo "✔ Nodo iniciado. Debería aparecer «en línea» en el panel en unos segundos."
echo "  Logs:     docker compose -f docker-compose.worker.yml --env-file worker.env logs -f"
echo "  Detener:  ./setup-worker.sh --down"
