# PLAN.md — Fase 1: Skeleton local (venv, árbol, health, README)

> **REGLA OBLIGATORIA PARA TODOS LOS AGENTES:**
> Antes de ejecutar cualquier paso, leer y acatar [`AGENTS.md`](./AGENTS.md) y `.cursor/rules/`.
> Este archivo es el **único plan ejecutable**. Describe **una sola fase**. Cuando esta fase esté cerrada, EsrgaN **reescribe** `PLAN.md` entero para la siguiente. No implementar Celery, Redis, Alembic, Token Bucket, send, métricas ni Docker porque “van después” en la constitución.

> **Cómo está pensado este documento (como CatalogoVentas):**
> Un agente “tonto” debe poder implementarlo **sin inventar**. Cada paso dice: archivos exactos, contrato de código, comando, test, commit propuesto y qué **no** tocar.
> Política anti-pereza: código completo y funcional. Cero placeholders, cero `# ... rest of code ...`, cero `pass` que finjan una feature, cero archivos “por si acaso” fuera de la lista de esta fase.

> **Estado de partida (inspeccionado):**
> El directorio del repo contiene `AGENTS.md`, este `PLAN.md` y `.cursor/rules/*.mdc`. **No hay** `.git`, `pyproject.toml`, `app/`, `tests/`, `README.md`, `.venv` ni Dockerfiles. Python del sistema: **3.12.3**. Gestor: **`uv` 0.12.0**. Postgres Homebrew 14 existe en la máquina pero **esta fase no lo usa**. Docker daemon no hace falta y **no se debe arrancar**.

---

## 0. Decisiones congeladas (esta fase)

Si un paso parece contradecirlas, manda esta tabla.

| # | Decisión | Valor congelado |
| --- | --- | --- |
| D1 | Aislamiento | Virtualenv local con `uv`. No Poetry. No `pip install` al Python del sistema. |
| D2 | Paquete | El código vive en `app/`, no en `src/` ni `backend/`. |
| D3 | Runtime de esta fase | FastAPI + Uvicorn + Pydantic v2 settings **mínimos**. No SQLAlchemy, no Alembic, no Celery, no Redis, no httpx de producción. |
| D4 | Health | `GET /health` **sin** prefijo `/api/v1`. Respuesta **200** `{"status": "ok"}`. Las rutas de producto (`/api/v1/...`) **no existen todavía**. |
| D5 | App factory | `create_app() -> FastAPI` en `app/main.py`. Además `app = create_app()` al final del módulo para `uvicorn app.main:app`. Los tests llaman a `create_app()`, no reutilizan un singleton sucio. |
| D6 | Settings | `app/core/config.py` con `app_name` y `environment` y defaults. **Ningún campo requerido** (`DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`) en esta fase: si se exige, `/health` no arranca. `extra="ignore"`. |
| D7 | Árbol | Se crean los paquetes vacíos del contrato (`domain`, `models`, `workers`, …) **solo** con `__init__.py` (docstring de una línea). No se crean `models.py` falsos ni `tasks.py` vacíos con `pass`. |
| D8 | Docker | **Prohibido** en esta fase: ni `Dockerfile`, ni `docker-compose.yml`, ni `docker pull`, ni `docker compose`. |
| D9 | Git | El repo **aún no está inicializado**. Esta fase hace `git init` y deja `main` como rama inicial. Commits **solo si EsrgaN lo pide**. Cada paso tiene el mensaje exacto listo. |
| D10 | README | Flujo **local** (venv, uvicorn, pytest). Docker se menciona en una línea: “no forma parte de esta fase”. |
| D11 | Idioma | Explicar a EsrgaN en español. Código, comentarios, commits, README técnico en **inglés**. |
| D12 | Enseñanza | Al cerrar la fase: 3–6 learning points. En cada archivo nuevo: una frase de responsabilidad (comentario de módulo o explicación en el chat). |

---

## 1. Diagnóstico del estado actual

No hay aplicación que romper. Los únicos riesgos son **inventar stack** o **saltar fases**.

1. Sin `.gitignore` + sin `.git` = si alguien hace `git init && git add .` después de crear `.venv`, se versiona el entorno. Por eso el `.gitignore` va **antes** de `uv venv` y **antes** de `git add`.
2. Sin `pyproject.toml` no hay instalación editable: `import app` fallaría en pytest.
3. Postgres y Redis de la máquina **no se tocan**. Health no abre sockets a ellos.

---

## 2. Arquitectura objetivo al cerrar esta fase

Esto es el árbol **final de la Fase 1**. Si un archivo no está aquí, **no se crea**. Si falta alguno de aquí, la fase no está cerrada.

```text
notifications-engine/
├── AGENTS.md                          # ya existe — NO reescribir
├── PLAN.md                            # este archivo — NO reescribir salvo typo
├── .cursor/rules/                     # ya existe — NO tocar
├── .gitignore                         # NUEVO
├── .env.example                       # NUEVO
├── pyproject.toml                     # NUEVO
├── README.md                          # NUEVO
├── app/
│   ├── __init__.py
│   ├── main.py                        # create_app + app
│   ├── api/
│   │   ├── __init__.py
│   │   ├── middleware/
│   │   │   └── __init__.py            # paquete vacío (rate-limit vendrá en otro PLAN)
│   │   └── routers/
│   │       ├── __init__.py
│   │       └── health.py              # GET /health
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py                  # Settings mínimos
│   ├── domain/__init__.py
│   ├── schemas/__init__.py
│   ├── models/__init__.py
│   ├── repositories/__init__.py
│   ├── services/__init__.py
│   ├── workers/__init__.py
│   └── providers/__init__.py
└── tests/
    ├── conftest.py
    ├── unit/
    │   └── .gitkeep                   # el directorio debe existir; sin tests de dominio aún
    └── integration/
        └── test_health.py
```

**No aparecen:** `alembic.ini`, `alembic/`, `Dockerfile`, `docker-compose.yml`, `app/api/deps.py`, modelos SQLAlchemy, tasks Celery.

Flujo HTTP de esta fase:

```text
GET /health  -->  health.router  -->  {"status": "ok"}  200
```

No hay persistencia, no hay auth, no hay cola.

---

## 3. Convención Git de esta fase

1. `git init` con rama `main` (paso 1.1).
2. Trabajar en `feat/phase-1-skeleton` (paso 1.1).
3. **Un commit por paso** (1.2, 1.3, 1.4, 1.5, 1.6, 1.7) **solo cuando EsrgaN lo autorice**. Si no lo autoriza, dejar el diff y mostrar el mensaje propuesto.
4. Nunca `git add .venv`, nunca `.env`, nunca `--no-verify`.
5. Mensajes en inglés, Conventional Commits, tal cual están escritos abajo (no “mejorarlos”).

Verificación **antes de dar un paso por cerrado**:

```bash
source .venv/bin/activate   # si no está activo
pytest
```

A partir del paso 1.5 (cuando exista el test de health), `pytest` debe quedar en verde. Antes, el comando puede no tener tests: no inventar tests dummy.

---

## FASE 0 — Preparación (sin commit de producto)

> **Rama:** ninguna todavía.
> **Objetivo:** confirmar la máquina. Si algo falla, **detenerse** y decirle a EsrgaN qué falta. No instalar Docker. No instalar Redis.

- [ ] **Paso 0.1** — Python 3.12:

```bash
python3 --version
# Esperado: Python 3.12.x
```

- [ ] **Paso 0.2** — uv:

```bash
uv --version
# Esperado: uv 0.x
```

- [ ] **Paso 0.3** — Confirmar que **no** vamos a usar Docker ni Redis:

```bash
# No ejecutar: docker compose, docker pull, brew install redis
pwd
# Debe terminar en .../notifications-engine
```

- [ ] **Paso 0.4** — Listar lo que ya existe (solo lectura):

```bash
ls -la
# Debe verse AGENTS.md, PLAN.md, .cursor/
```

**Checklist Fase 0**
- [ ] Python 3.12.x
- [ ] `uv` disponible
- [ ] CWD = `notifications-engine`
- [ ] Cero contenedores arrancados por el agente

---

## FASE 1 — Skeleton

> **Rama:** `feat/phase-1-skeleton`
> **Objetivo:** un paquete instalable, FastAPI que responde `/health`, tests verdes, README de flujo local.
> **Regla de oro:** no se implementa ninguna regla de negocio de notificaciones. Solo cimientos.

### Paso 1.1 — `git init` y rama

En la raíz del proyecto:

```bash
git init -b main
git checkout -b feat/phase-1-skeleton
```

No hacer el commit inicial todavía (aún no hay `.gitignore` ni código). Si `git init` ya existiera (no es el caso hoy), no volver a inicializar: solo crear/cambiar a `feat/phase-1-skeleton`.

- [ ] Repo git existe
- [ ] Rama actual = `feat/phase-1-skeleton`
- **Commit:** ninguno

---

### Paso 1.2 — `.gitignore`

Crear [`.gitignore`](.gitignore) en la raíz con **exactamente** este contenido (se pueden añadir líneas extra de editores tipo `.DS_Store`, nada más):

```gitignore
# Virtualenv and secrets
.venv/
.env
.env.local

# Python
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
build/

# OS / editor
.DS_Store
.idea/
.vscode/
```

- [ ] `.venv/` está ignorado
- [ ] `.env` está ignorado
- **Commit (si EsrgaN autoriza):**

```text
chore: add gitignore before the virtualenv exists

Keep .venv and secrets out of the first commit.
```

---

### Paso 1.3 — `pyproject.toml`

Crear [`pyproject.toml`](pyproject.toml) en la raíz con **este contrato** (versiones pueden usar el límite inferior indicado; no subir a FastAPI 1.x ni a Pydantic v1; no añadir Celery/SQLAlchemy/Redis):

```toml
[project]
name = "notifications-engine"
version = "0.1.0"
description = "Multichannel notifications engine with distributed rate limiting"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115,<1",
    "uvicorn[standard]>=0.32,<1",
    "pydantic-settings>=2.6,<3",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3,<9",
    "pytest-asyncio>=0.24,<1",
    "httpx>=0.27,<1",
    "ruff>=0.8,<1",
    "mypy>=1.13,<2",
]

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["app*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["app"]
```

**Por qué setuptools y no Poetry:** `uv` instala desde `pyproject.toml`; Poetry duplicaría el lock y el flujo. **Por qué `httpx` en dev:** `TestClient` de Starlette/FastAPI lo necesita.

Todavía **no** crear el venv en este paso si EsrgaN quiere commits atómicos: el archivo puede existir sin instalar. La instalación es el paso 1.4.

- [ ] `requires-python = ">=3.12"`
- [ ] Cero deps de Celery, Redis, SQLAlchemy, Alembic
- **Commit (si EsrgaN autoriza):**

```text
chore: add pyproject with FastAPI and pytest for local venv

Make the engine an installable 3.12 package before any domain code.
```

---

### Paso 1.4 — venv e instalación editable

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
python -c "import fastapi; import app; print('ok')"
```

`import app` fallará hasta que existan `app/__init__.py` y el paquete. **Orden obligatorio dentro de este paso:**

1. Crear **todos** los `__init__.py` de la sección 2 (contenido: una sola línea de docstring, nada más). Ejemplo de `app/__init__.py`:

```python
"""Notifications engine application package."""
```

Ejemplo de `app/domain/__init__.py`:

```python
"""Domain layer: enums, state machine, exceptions. Empty in phase 1."""
```

Misma idea para: `app/api`, `app/api/middleware`, `app/api/routers`, `app/core`, `app/schemas`, `app/models`, `app/repositories`, `app/services`, `app/workers`, `app/providers`.

2. Crear `tests/unit/.gitkeep` (archivo vacío) para que git conserve el directorio.
3. Recién entonces `uv venv` + `uv pip install -e ".[dev]"` si el venv no existía, o reinstall si ya existía.
4. Confirmar:

```bash
which python
# Debe apuntar a .../notifications-engine/.venv/bin/python
python -c "import fastapi; print(fastapi.__version__)"
```

- [ ] `.venv/` existe y está gitignored
- [ ] `which python` es el del `.venv`
- [ ] Todos los paquetes de la sección 2 tienen `__init__.py`
- [ ] No hay `app/utils.py` ni `helpers.py`
- **Commit (si EsrgaN autoriza):** incluir `__init__.py` y `.gitkeep`, **nunca** `.venv`:

```text
chore: add package layout and local uv virtualenv

Reserve the AGENTS.md folder contract so later phases do not invent src/.
```

---

### Paso 1.5 — Settings mínimos + app factory + `/health`

Crear los tres módulos siguientes. Código **completo**, sin omisiones.

**a) [`app/core/config.py`](app/core/config.py)**

- `Settings` hereda de `pydantic_settings.BaseSettings`.
- `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")`.
- Campos: `app_name: str = "notifications-engine"`, `environment: str = "local"`.
- `get_settings()` decorado con `functools.lru_cache` para no reler el env en cada request.
- **No** añadir `database_url` ni `redis_url` todavía.

**b) [`app/api/routers/health.py`](app/api/routers/health.py)**

- `APIRouter(tags=["health"])`.
- Función **síncrona** `health() -> dict[str, str]` (no hay I/O; no usar `async def` de adorno).
- Ruta `GET /health` → `{"status": "ok"}`.

**c) [`app/main.py`](app/main.py)**

```python
from fastapi import FastAPI

from app.api.routers.health import router as health_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    """Application factory so tests get a clean app instance."""
    settings = get_settings()
    application = FastAPI(title=settings.app_name, version="0.1.0")
    application.include_router(health_router)
    return application


app = create_app()
```

No incluir routers que no existen. No montar middleware. No conectar DB.

Comprobar a mano (dejar Uvicorn **sin** `--reload` colgado al final; o arrancar, curl, parar):

```bash
uvicorn app.main:app --port 8000
# en otro terminal:
curl -s http://127.0.0.1:8000/health
# Esperado: {"status":"ok"}
```

- [ ] `GET /health` = 200 y JSON exacto
- [ ] No existe `POST /api/v1/notifications/send`
- **Commit (si EsrgaN autoriza):**

```text
feat: add FastAPI app factory and health endpoint

Prove the HTTP process boots before domain or IO exist.
```

---

### Paso 1.6 — Tests de health

**a) [`tests/conftest.py`](tests/conftest.py)**

- Fixture `client` que hace `TestClient(create_app())` y hace `yield`.
- Importar `TestClient` de `fastapi.testclient`.
- Tipar la fixture. No crear DB ni Redis.

**b) [`tests/integration/test_health.py`](tests/integration/test_health.py)**

Un solo test (nombre exacto sugerido: `test_health_returns_ok`):

- `client.get("/health")`
- `status_code == 200`
- `response.json() == {"status": "ok"}`

Ejecutar:

```bash
pytest -q
```

Debe haber **1 passed** (o más si pytest recolecta algo extra: no debe haber failed). Si MyPy/Ruff están instalados, se pueden correr pero **no son puerta de esta fase** salvo errores evidentes introducidos por nosotros:

```bash
ruff check app tests
```

- [ ] `pytest -q` verde
- [ ] El test usa `TestClient`, no `requests` contra localhost
- **Commit (si EsrgaN autoriza):**

```text
test: cover health endpoint with FastAPI TestClient

Lock the first integration path before real product routes exist.
```

---

### Paso 1.7 — `.env.example` y `README.md`

**a) [`.env.example`](.env.example)** — placeholders, **no secretos reales**:

```env
APP_NAME=notifications-engine
ENVIRONMENT=local
# Persistence / Redis arrive in later PLAN.md rewrites. Unused in phase 1.
# DATABASE_URL=postgresql+psycopg://USER@localhost:5432/notifications_engine
# REDIS_URL=redis://localhost:6379/0
# SECRET_KEY=change-me
```

**b) [`README.md`](README.md)** — en inglés, corto, útil. Secciones **obligatorias**:

1. Título y párrafo: qué es el engine (notificaciones multicanal, cola, rate limit) y que el desarrollo actual es **local venv**.
2. Diagrama mermaid **objetivo** (API → service → Postgres / Redis → worker → providers). Aclarar que hoy solo existe `/health`.
3. Prerequisites: Python 3.12, `uv`. Postgres/Redis “later phases”.
4. Setup exacto:

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
```

5. Run: `uvicorn app.main:app --reload --port 8000` y `curl http://127.0.0.1:8000/health`
6. Tests: `pytest`
7. Docker: una frase — not in this phase; will be a later PLAN rewrite.

No copiar `AGENTS.md` entero al README.

- [ ] README permite a un extraño levantar `/health` sin Docker
- [ ] `.env.example` no contiene passwords reales
- **Commit (si EsrgaN autoriza):**

```text
docs: add README and env example for local venv workflow

Document uv/uvicorn/pytest as the default loop; defer Compose.
```

---

## 4. Checklist de cierre de la Fase 1

Un agente **no** declara la fase terminada si falta un ítem.

- [ ] `git status` no muestra `.venv/` ni `.env` como untracked que vayamos a añadir
- [ ] Árbol de la sección 2 completo; **cero** Dockerfiles / Alembic
- [ ] `which python` → `.venv/bin/python`
- [ ] `pytest -q` verde (`test_health_returns_ok`)
- [ ] `curl` o TestClient: `GET /health` → 200 `{"status":"ok"}`
- [ ] `ruff check app tests` sin errores introducidos (si se corre)
- [ ] README con setup local
- [ ] Al usuario: 3–6 learning points en español (venv, app factory, por qué health no va bajo `/api/v1`, por qué el árbol vacío, por qué no Docker)
- [ ] Commits de los pasos 1.2–1.7 hechos **o** mensajes propuestos esperando a EsrgaN

**Prohibido al “terminar”:** empezar modelos, `POST /send`, instalar `celery`/`redis`/`sqlalchemy`, escribir `Dockerfile`.

---

## 5. Qué pasa después (no implementar)

Cuando EsrgaN cierre esta fase, **se reemplaza este `PLAN.md`** por el de la siguiente (settings fail-fast + logging estructurado, o lo que él pida). El mapa largo sigue en `AGENTS.md` §10.1 como brújula, no como lista de tareas.

No fusionar a `main` ni pushear a menos que EsrgaN lo pida explícitamente.
