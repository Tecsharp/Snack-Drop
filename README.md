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

   Sin Docker, video y audio funcionan gracias al ffmpeg empaquetado; OCR y Office → PDF requieren instalar
   Tesseract/Ghostscript o LibreOffice en esa computadora.

   Para actualizar un nodo ya configurado basta con `git pull` y `./setup-worker.sh` (reutiliza `worker.env`).

Si la otra computadora no conecta, revisa que el firewall del servidor permita entrada TCP al puerto `28743`
(o el que elegiste con `--port`) y que ambas estén en la misma red (o usa una VPN como Tailscale).

El agente solo abre una conexión **saliente** (WebSocket + HTTP) hacia el servidor. No expone puertos ni el escritorio,
y solo ejecuta operaciones del catálogo. Su dueño puede limitarlas aún más con `--allow image.convert`.

### Usar la computadora de otra persona

Cada nodo pertenece a quien lo crea. El dueño autoriza a otros usuarios en **Nodos → Usuarios autorizados** y puede
pausar, revocar o eliminar el nodo en cualquier momento. Un administrador puede marcar un nodo como disponible para todos.

## Operaciones

Todas se eligen en **Nuevo trabajo** (o escribiéndolas al asistente). Cada nodo anuncia solo las que puede ejecutar;
si ninguno conectado puede, el trabajo espera en la cola.

| Categoría | Operaciones |
|-----------|-------------|
| **Imágenes** | Convertir (WebP/JPEG/PNG/AVIF) · HEIC de iPhone → JPEG/WebP · AVIF · Marca de agua · Recortar a proporción (encuadre inteligente) · Quitar metadatos EXIF/GPS (JPEG sin recomprimir) · Renombrar por fecha · Quitar fondo (IA) · Ampliar x2/x3/x4 (IA) |
| **PDF** | Comprimir · Unir · Separar por páginas/rangos · Imágenes → PDF · PDF → imágenes · Rotar · Proteger con contraseña (AES-256) · Quitar contraseña · OCR (español/inglés) · Marca de agua |
| **Video** | Comprimir H.264/H.265 · Convertir MKV/AVI/MOV → MP4/WebM (sin recodificar si se puede) · Cambiar resolución · Extraer audio · Video → GIF/WebP animado · Miniaturas |
| **Audio** | Convertir (MP3/AAC/Opus/FLAC/WAV) · Normalizar volumen (EBU R128) · Transcribir a texto/subtítulos (Whisper, IA) |
| **Documentos y archivos** | Office → PDF · Comprimir en ZIP/7z (7z con contraseña) · Descomprimir ZIP/7z/TAR · Calcular SHA-256/MD5 |

- **Lotes:** cada trabajo acepta cientos de archivos; un archivo dañado se omite y el resto se entrega. Las operaciones
  de lote (unir, ZIP, renombrar, hash, imágenes → PDF) procesan todos juntos.
- **GPU:** los nodos con Nvidia (NVENC) o Mac (VideoToolbox) codifican video por hardware, y el despacho les da
  preferencia para video e IA.
- **Contraseñas** de PDF/7z: viajan al nodo solo mientras el trabajo corre; la API nunca las muestra y se borran de la
  base de datos al terminar.
- **Asistente DeepSeek**: escribe «comprime este video en h265 a 1080p en SHRIMPDADDY» y se rellena el trabajo. La
  respuesta se valida contra el catálogo; nunca se ejecuta texto libre. Sin API key se usa un intérprete local.

### Extras del nodo

La imagen base del nodo trae ffmpeg, Ghostscript y Tesseract. Dos extras pesados son opcionales:

| Extra | Habilita | Tamaño aprox. | Servidor | Otra computadora |
|-------|----------|---------------|----------|------------------|
| Office | Word/Excel/PowerPoint → PDF | +600 MB | `./setup.sh --with-office` | `./setup-worker.sh --with-office` |
| IA | Quitar fondo, ampliar, transcribir | +1.5 GB | `./setup.sh --with-ai` | `./setup-worker.sh --with-ai` |

Los modelos de IA se descargan al construir la imagen (con hash verificado), así el nodo funciona sin internet.
Dentro de Docker la IA corre en CPU; para usar la GPU Nvidia con IA ejecuta el nodo sin Docker
(`pip install -r requirements.txt -r requirements-ai.txt`).

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
