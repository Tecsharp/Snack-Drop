# Snack-Drop

Plataforma para distribuir y ejecutar tareas de procesamiento entre computadoras autorizadas, con seguimiento en tiempo real y sin necesidad de acceder remotamente a sus escritorios.

> Tienes 200 fotografías que necesitan convertirse a WebP. Tu computadora es lenta, pero otra que tienes en casa está encendida.
> Arrastras las imágenes, eliges **Convertir a WebP** y seleccionas dónde ejecutar el trabajo. La computadora ejecutora
> devuelve los resultados, sin que tengas que acceder remotamente a su escritorio.

## Inicio rápido

Requisitos: Docker con Docker Compose v2.

```bash
./setup.sh
```

El script:

1. Genera `.env` (permisos `600`) con una clave secreta, una **contraseña aleatoria para `admin`** y el token del nodo local.
2. Construye e inicia los contenedores (`backend`, `frontend`, `worker`).
3. Espera a que el servidor responda y muestra la URL y las credenciales.

Abre `http://localhost:28743`, entra como `admin` con la contraseña mostrada y cámbiala en **Cuenta**.

Opciones: `./setup.sh --port 9000`, `./setup.sh --deepseek-key sk-…`, `./setup.sh --yes` (sin preguntas), `./setup.sh --down`.

## Sumar otra computadora

1. En la interfaz, ve a **Nodos → Agregar computadora**. Se genera un token (se muestra una sola vez).
2. En la otra computadora, clona este repositorio y ejecuta el comando mostrado:

   ```bash
   ./setup-worker.sh --server http://IP-DEL-SERVIDOR:28743 --token sdn_xxx
   ```

   Sin Docker (Windows/macOS/Linux con Python 3.11+):

   ```bash
   cd worker
   pip install -r requirements.txt
   SNACKDROP_SERVER=http://IP-DEL-SERVIDOR:28743 SNACKDROP_TOKEN=sdn_xxx python -m snackdrop_worker
   ```

Si la otra computadora no conecta, revisa que el firewall del servidor permita entrada TCP al puerto `28743`
(o el que elegiste con `--port`) y que ambas estén en la misma red (o usa una VPN como Tailscale).

El agente solo abre una conexión **saliente** (WebSocket + HTTP) hacia el servidor. No expone puertos ni el escritorio,
y solo ejecuta operaciones del catálogo. Su dueño puede limitarlas aún más con `--allow image.convert`.

### Usar la computadora de otra persona

Cada nodo pertenece a quien lo crea. El dueño autoriza a otros usuarios en **Nodos → Usuarios autorizados** y puede
pausar, revocar o eliminar el nodo en cualquier momento. Un administrador puede marcar un nodo como disponible para todos.

## Funciones (MVP)

| Operación | Detalle |
|-----------|---------|
| `image.convert` | JPEG/PNG/WebP/BMP/TIFF/GIF → WebP, JPEG o PNG; calidad, sin pérdida, redimensionado máximo, quitar EXIF/GPS. |
| `pdf.compress` | Ghostscript (`/printer`, `/ebook`, `/screen`) con opción de escala de grises; respaldo con pikepdf. |
| Lotes | Cada trabajo acepta cientos de archivos; los resultados se descargan como ZIP. |

- **Tiempo real (WebSockets)**: disponibilidad de nodos, cola, progreso por etapa (descarga → proceso → subida) y logs en vivo.
- **Asistente DeepSeek**: escribe «convierte a WebP calidad 75, máx 1920px, en SHRIMPDADDY» y se rellena el trabajo.
  La respuesta del modelo se valida contra el catálogo; nunca se ejecuta texto libre. Sin API key se usa un intérprete local.
- **Cola y despacho**: modo automático (primer nodo libre compatible) o nodo específico; pausa por nodo o global;
  si un nodo se desconecta, su trabajo vuelve a la cola.

## Archivos y limpieza

- **Nodo ejecutor:** cada trabajo usa una carpeta temporal que se borra al terminar (éxito, fallo o cancelación).
- **Originales en el servidor:** se borran en cuanto el trabajo termina (`SNACKDROP_DELETE_INPUTS_ON_FINISH=true`).
- **Resultados:** se pueden descargar durante `SNACKDROP_RETENTION_DAYS` días (7 por defecto; `0` = para siempre).
  Después, el trabajo y sus archivos se eliminan automáticamente (revisión cada hora). También puedes borrarlos antes
  con el icono de basura.
- **Archivos que fallan:** el lote continúa; la tarjeta del trabajo lista cada archivo omitido con su motivo.

Cambia estos valores en `.env` y aplica con `./setup.sh`.

## Seguridad

- Sin registro público: el administrador crea las cuentas con contraseña temporal y el usuario debe cambiarla al entrar.
- Contraseñas con **Argon2id**; política mínima (10 caracteres, 3 tipos de carácter, sin incluir el usuario).
- Sesión JWT en cookie `HttpOnly` + `SameSite=Strict` (activa `SNACKDROP_COOKIE_SECURE=true` detrás de HTTPS).
  Cambiar contraseña, desactivar o cambiar rol invalida las sesiones existentes.
- Bloqueo temporal tras intentos fallidos (por usuario y por IP) y verificación de tiempo constante para usuarios inexistentes.
- Cabecera anti-CSRF obligatoria en peticiones que modifican datos y verificación de `Origin` en el WebSocket.
- Tokens de nodo de 256 bits guardados como hash SHA-256; se pueden rotar.
- Cabeceras CSP, `X-Frame-Options`, `nosniff`; contenedores sin root; el backend no se expone fuera de la red de Docker.

## Arquitectura

```
navegador ──HTTP/WS──► frontend (nginx + React/Vite) ──► backend (FastAPI, SQLite en volumen)
                                                            ▲
             worker local (docker) ──WS + HTTP──────────────┤
             worker en otra computadora ──WS + HTTP─────────┘
```

| Carpeta | Contenido |
|---------|-----------|
| `backend/` | FastAPI, SQLAlchemy, autenticación, catálogo, cola, WebSockets, asistente DeepSeek. |
| `worker/` | Agente ejecutor (`python -m snackdrop_worker`): Pillow, Ghostscript, pikepdf. |
| `frontend/` | React + Vite, servido por nginx que también hace de proxy de `/api` y `/ws`. |

## Desarrollo y pruebas

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-dev.txt -r worker/requirements-dev.txt
pytest backend/tests worker/tests      # incluye prueba extremo a extremo con un agente real

cd frontend && npm install && npm test && npm run build
```

Para desarrollo local: backend con `uvicorn app.main:create_app --factory` (variables `SNACKDROP_*`) y
`npm run dev` en `frontend/` (proxy a `localhost:8000`).
