# PLAN.md — Fase 2: Settings fail-fast y logging estructurado

> **REGLA OBLIGATORIA PARA TODOS LOS AGENTES:**
> Antes de ejecutar cualquier paso, leer y acatar [`AGENTS.md`](./AGENTS.md) y `.cursor/rules/`.
> Este archivo es el **único plan ejecutable**. Describe **una sola fase**. Cuando cierre, EsrgaN **reescribe** `PLAN.md` entero. No implementar dominio, SQLAlchemy, Alembic, Celery, Redis, Token Bucket, `POST /send`, métricas ni Docker.

> **Cómo está pensado este documento:**
> Un agente debe poder implementarlo **sin inventar**. Cada paso dice: archivos exactos, contrato de código, comando, test, commit propuesto y qué **no** tocar.
> Política anti-pereza: código completo y funcional. Cero placeholders, cero `# ... rest of code ...`, cero `pass` que finjan una feature.

> **Estado de partida (verificado en `feat/phase-1-skeleton`, commit `24f06db`):**
> Fase 1 **cerrada y verde**. `pytest -q` → 1 passed. `ruff check app tests` limpio. `GET /health` → 200 `{"status":"ok"}`. No hay Dockerfile ni Compose. Settings actuales son **fail-soft** (`app_name` / `environment` con default). `get_settings` usa `lru_cache`. `app = create_app()` se ejecuta al importar `app.main`. Postgres/Redis de la máquina **no se tocan**.

---

## 0. Decisiones congeladas (esta fase)

Si un paso parece contradecirlas, manda esta tabla.

| # | Decisión | Valor congelado |
| --- | --- | --- |
| D1 | Qué falla rápido **ahora** | `secret_key` es **obligatorio**. Tipo `pydantic.SecretStr`, `min_length=16`. Sin default. Sin `SECRET_KEY` (ni en env ni en `.env`), `Settings()` lanza `ValidationError` y el proceso **no arranca**. |
| D2 | Qué **no** se vuelve obligatorio aún | `DATABASE_URL` y `REDIS_URL` siguen **ausentes** del modelo. No conectamos a Postgres ni a Redis. Exigirlas ahora obligaría a mentir con URLs que nadie usa. El *patrón* fail-fast se enseña con `secret_key`. |
| D3 | `environment` | `Literal["local", "test", "production"]`, default `"local"`. Cualquier otro valor (p.ej. `dev`) → `ValidationError`. |
| D4 | `log_level` | `Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]`, default `"INFO"`. Aceptar minúsculas en el env y **normalizar a mayúsculas** con un `field_validator` `before`. |
| D5 | Logging | Solo stdlib `logging`. **No** instalar `structlog` ni `python-json-logger`. Formatter propio en `app/core/logging.py`. |
| D6 | Formato | `local` y `test` → texto en una línea (legible en terminal/pytest). `production` → **una línea JSON** por record (stdout). |
| D7 | Campos extra reservados | El formatter incluye, si vienen en el record: `request_id`, `notification_id`, `client_id`, `channel`, `status`, `retry_count`. Hoy casi siempre vendrá solo `request_id`. **Nunca** loguear `secret_key` ni headers `Authorization` / `X-API-Key`. |
| D8 | Request ID | Middleware ASGI o `BaseHTTPMiddleware` en `app/api/middleware/request_id.py`. Lee `X-Request-ID` o genera `uuid4`. Lo guarda en un `ContextVar`. Lo **devuelve** en la respuesta. Un `logging.Filter` copia el valor al record. |
| D9 | Lifespan | `create_app` registra un `lifespan` que llama `configure_logging(settings)` y emite `application_started` con `environment` (no el secreto). No usar `@app.on_event` (deprecado). |
| D10 | Health | Sigue `GET /health` → 200 `{"status":"ok"}`. **No** añadir `environment` al payload. **No** loguear cada hit de `/health` a INFO (Uvicorn ya hace access log). |
| D11 | Tests vs import de `app.main` | `app = create_app()` corre al importar. `tests/conftest.py` **debe** hacer `os.environ.setdefault("SECRET_KEY", ...)` **antes** de `from app.main import create_app`. Los unit tests de “falta el secreto” instancian `Settings(_env_file=None)` y **no** importan `app.main`. |
| D12 | Caché | Fixture `autouse` que hace `get_settings.cache_clear()` al entrar y al salir. Si no, un test deja Settings pegado al proceso. |
| D13 | Docker / Redis / SQLAlchemy / Celery / dominio | **Prohibidos.** No nuevos paquetes en `pyproject.toml`. |
| D14 | Git | Rama `feat/phase-2-settings-logging` desde el HEAD actual (`feat/phase-1-skeleton`). Commits **solo si EsrgaN lo pide**. Un commit por paso. No fusionar a `main` salvo que lo pida. |
| D15 | Enseñanza | Explicar en español. Al cerrar: 3–6 learning points. |

---

## 1. Diagnóstico del estado actual (por qué esta fase)

Auditoría sobre el código real de `feat/phase-1-skeleton`.

1. **`Settings` no puede fallar.** [`app/core/config.py`](app/core/config.py) solo tiene `app_name` y `environment` con default. Un `.env` vacío arranca igual. Eso viola `AGENTS.md` §6.3 *para secretos*; todavía no para URLs de IO (D2).
2. **`lru_cache` + `app = create_app()` al importar** implica: el primer `import app.main` congela Settings. Los tests de la fase 1 no limpian la caché porque no hacía falta. En cuanto `secret_key` sea obligatorio, el orden de `conftest.py` **es** el bug o el arreglo.
3. **No hay logging de aplicación.** Cualquier `print` futuro o logger sin configurar sale sin correlación. El `ContextVar` + filter es el gancho donde más adelante colgaremos `notification_id` sin reescribir los routers.
4. **Fase 1 OK (no revertir):** árbol `app/` correcto, health test verde, Ruff verde, README local, cero Docker. Un único commit de skeleton (en vez de un commit por paso) es aceptable; no reescribir historia.

Nits que **no** bloquean (el agente no tiene que “arreglar el mundo”): pueden existir `.DS_Store` locales (ya están en `.gitignore`). Hay un warning de Starlette/httpx en pytest: **no** pelearse con eso en esta fase.

---

## 2. Arquitectura objetivo al cerrar esta fase

Árbol **final**. Si un archivo no está en esta lista como NUEVO o EDITADO, no se crea. No borrar los `__init__.py` vacíos de dominio/models/etc.

```text
notifications-engine/
├── AGENTS.md                          # no tocar
├── PLAN.md                            # este archivo
├── .env.example                       # EDITAR: SECRET_KEY obligatorio
├── README.md                          # EDITAR: arranque exige SECRET_KEY
├── pyproject.toml                     # NO tocar dependencias
├── app/
│   ├── main.py                        # EDITAR: lifespan + middleware
│   ├── core/
│   │   ├── config.py                  # EDITAR: secret_key, environment, log_level
│   │   └── logging.py                 # NUEVO
│   └── api/
│       └── middleware/
│           ├── __init__.py            # puede reexportar el middleware (opcional)
│           └── request_id.py          # NUEVO
├── tests/
│   ├── conftest.py                    # EDITAR: env + cache_clear ANTES del import
│   ├── unit/
│   │   ├── test_config.py             # NUEVO
│   │   └── test_logging.py            # NUEVO
│   └── integration/
│       ├── test_health.py             # no romper
│       └── test_request_id.py         # NUEVO
```

Flujo de arranque:

```text
import/create_app
  -> get_settings()          # ValidationError si falta SECRET_KEY
  -> FastAPI(lifespan=...)
  -> add RequestIdMiddleware
  -> include health
lifespan startup
  -> configure_logging(settings)
  -> log application_started  # sin secret_key
GET /health
  -> middleware asigna request_id
  -> {"status":"ok"} + header X-Request-ID
```

---

## 3. Convención Git de esta fase

```bash
git checkout feat/phase-1-skeleton    # si no estás ahí
git checkout -b feat/phase-2-settings-logging
```

Si la rama ya existe, usarla; no recrearla.

Verificación **antes de cerrar cada paso que toque código**:

```bash
source .venv/bin/activate
pytest -q
ruff check app tests
```

`pytest` debe seguir incluyendo `test_health_returns_ok` en verde.

---

## FASE 0 — Preparación (sin commit de producto)

- [ ] **Paso 0.1** — Rama correcta y árbol limpio de Docker:

```bash
git status -sb
# esperado: feat/phase-1-skeleton o ya feat/phase-2-settings-logging
ls Dockerfile docker-compose.yml
# esperado: No such file
```

- [ ] **Paso 0.2** — Baseline verde **antes** de tocar código:

```bash
source .venv/bin/activate
pytest -q
ruff check app tests
```

Si esto falla, **detenerse**. No empezar la Fase 2 sobre un skeleton roto.

- [ ] **Paso 0.3** — Crear la rama `feat/phase-2-settings-logging` desde el HEAD del skeleton.

**Checklist Fase 0**
- [ ] pytest verde (1+ passed)
- [ ] ruff verde
- [ ] rama de fase creada
- [ ] cero contenedores arrancados por el agente

---

## FASE 2 — Settings fail-fast + logging

> **Objetivo:** el proceso **no arranca** sin `SECRET_KEY`; los logs son estructurados y correlacionables con `X-Request-ID`; `/health` sigue igual.
> **Regla de oro:** no se añade IO real (DB, Redis, proveedores).

### Paso 2.1 — `Settings` fail-fast

Editar [`app/core/config.py`](app/core/config.py). Reemplazar el modelo mínimo de la fase 1. Contrato exacto:

- Seguir usando `pydantic_settings.BaseSettings` y `SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")`.
- Campos:
  - `app_name: str = "notifications-engine"`
  - `environment: Literal["local", "test", "production"] = "local"`
  - `log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"`
  - `secret_key: SecretStr` — **sin default**. `Field(min_length=16)`.
- Validator `mode="before"` sobre `log_level`: si llega `str`, hacer `.upper()`. Así `log_level=info` en `.env` funciona.
- `get_settings()` sigue con `@lru_cache` y `return Settings()`.
- Docstring del módulo: explicar **por qué** `DATABASE_URL` no está aún (no hay IO; no mentir).
- `SecretStr` para que `repr(settings)` no imprima el secreto.

No añadir `database_url`. No añadir `redis_url`.

Editar [`.env.example`](.env.example) para que `SECRET_KEY` esté **descomentado** y tenga ≥16 caracteres de placeholder, p.ej.:

```env
APP_NAME=notifications-engine
ENVIRONMENT=local
LOG_LEVEL=INFO
SECRET_KEY=dev-secret-change-me
# Unused until later PLAN.md rewrites (we do not connect yet):
# DATABASE_URL=postgresql+psycopg://USER@localhost:5432/notifications_engine
# REDIS_URL=redis://localhost:6379/0
```

Si EsrgaN tiene un `.env` local, **no commitearlo**. En el chat, recordarle que copie el nuevo `SECRET_KEY` o `uvicorn` morirá al arrancar. El agente puede crear `.env` local **solo si no existe**, copiando `.env.example`; sigue gitignored.

- [ ] `Settings(_env_file=None)` sin `SECRET_KEY` en el entorno lanza `ValidationError`
- [ ] `secret_key` no aparece en claro en `repr(Settings(...))`
- **Commit (si EsrgaN autoriza):**

```text
feat: require a secret key so the app fails fast on boot

Refuse to start with a missing or short SECRET_KEY instead of
running with silent empty config.
```

---

### Paso 2.2 — Tests unitarios de Settings + conftest a prueba de import

**Orden en [`tests/conftest.py`](tests/conftest.py) (crítico):**

1. `import os` y `os.environ.setdefault("SECRET_KEY", "pytest-secret-key")` (≥16 chars).
2. `os.environ.setdefault("ENVIRONMENT", "test")`.
3. **Después** de eso: `from app.core.config import get_settings` y `from app.main import create_app`.
4. Fixture `autouse=True` `_reset_settings_cache` que llama `get_settings.cache_clear()` before/after.

Si se importa `app.main` arriba del `setdefault`, `create_app()` explota o congela un Settings viejo. Ese es el bug de D11.

Crear [`tests/unit/test_config.py`](tests/unit/test_config.py):

1. `test_missing_secret_key_fails_fast(monkeypatch)`  
   - `monkeypatch.delenv("SECRET_KEY", raising=False)`  
   - `with pytest.raises(ValidationError): Settings(_env_file=None)`  
   - **No** importar `create_app` en este test.

2. `test_secret_key_shorter_than_16_fails(monkeypatch)`  
   - `monkeypatch.setenv("SECRET_KEY", "short")`  
   - `Settings(_env_file=None)` → `ValidationError`.

3. `test_valid_secret_key_is_not_in_repr(monkeypatch)`  
   - `monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")`  
   - `s = Settings(_env_file=None)`  
   - `assert "pytest-secret-key" not in repr(s)`  
   - `assert s.secret_key.get_secret_value() == "pytest-secret-key"`

4. `test_invalid_environment_fails(monkeypatch)`  
   - `SECRET_KEY` válido + `ENVIRONMENT=dev` → `ValidationError`.

5. `test_log_level_is_normalized_to_uppercase(monkeypatch)`  
   - `LOG_LEVEL=info` → `settings.log_level == "INFO"`.

Ejecutar `pytest -q`. Health sigue verde.

- [ ] Unit tests de config en verde
- [ ] `test_health_returns_ok` sigue en verde
- **Commit (si EsrgaN autoriza):**

```text
test: cover fail-fast settings and isolate Settings from .env

Lock boot-time ValidationError and keep TestClient imports from
crashing once SECRET_KEY is required.
```

---

### Paso 2.3 — Logging estructurado

Crear [`app/core/logging.py`](app/core/logging.py). Contrato:

**a) `request_id_ctx: ContextVar[str]`**

- Default `"-"`.
- Definirla **aquí** (un solo sitio). El middleware del paso 2.4 solo hace `.set()` / `.reset()`.

**b) `class RequestIdFilter(logging.Filter)`**

- `filter(self, record)`: `record.request_id = request_id_ctx.get()` y `return True`.
- Así ningún `logger.info` tiene que acordarse del request id.

**c) Formatters**

- Texto (local/test): incluir asctime, level, name, request_id, message. Si el record trae `notification_id` / `client_id` / `channel` / `status` / `retry_count`, añadirlos al final como `key=value`. No imprimir claves ausentes.
- JSON (production): `json.dumps` de un dict con `timestamp`, `level`, `logger`, `message`, `request_id`, y las mismas claves extra **solo si existen**. `ensure_ascii=True`, una línea, `default=str`. Nunca incluir `secret_key`.

**d) `configure_logging(settings: Settings) -> None`**

- Idempotente: si el logger `"app"` (o el root que elijáis — **congelado: logger `"app"`** y también configurar el root para no perder logs de librerías a WARNING) ya tiene nuestros handlers, **no duplicar**. Receta simple y obligatoria:
  1. `root = logging.getLogger()`
  2. `root.handlers.clear()`
  3. nivel desde `settings.log_level`
  4. un `StreamHandler(sys.stdout)` con el formatter según `settings.environment`
  5. añadir `RequestIdFilter()` al handler
- No usar `basicConfig` a medias y esto a la vez (doble handler).
- No loguear el `secret_key`.

**e) Logger de aplicación**

- Convención: `logging.getLogger("app")` o `logging.getLogger(__name__)` dentro de `app.*`. Con root configurado, ambos salen.

Unit tests en [`tests/unit/test_logging.py`](tests/unit/test_logging.py):

1. Construir `Settings(_env_file=None)` con `SECRET_KEY` de test y `ENVIRONMENT=production`, `LOG_LEVEL=INFO`.
2. `configure_logging(settings)`.
3. Usar un `StreamHandler` sobre `io.StringIO` **o** inspeccionar el handler que `configure_logging` acaba de colgar del root: loguear `logging.getLogger("app").info("hello", extra={"channel": "email"})`.
4. Assert: el output JSON (`json.loads` de la línea) tiene `message` / `channel` == `"email"` y **no** contiene el secreto.
5. Segundo test: `ENVIRONMENT=local` → el output **no** es JSON (no empieza por `{`), pero contiene `hello` y el `request_id` default `-` o el que se haya seteado.
6. `configure_logging` dos veces no duplica handlers (`len(root.handlers)` no crece sin control; tras dos llamadas debe quedar **1** StreamHandler nuestro, o el número estable que documentéis en el test).

Detalle: `handlers.clear()` en root puede silenciar pytest caplog. Por eso estos tests usan un `StringIO` enganchado **o** leen `handler.stream` tras configurar. Si hace falta, en tests de logging no uses `caplog` como única fuente.

- [ ] JSON en production; texto en local
- [ ] `extra={"channel": "email"}` sobrevive al formatter
- [ ] configure_logging idempotente
- **Commit (si EsrgaN autoriza):**

```text
feat: add structured logging with reserved correlation fields

Emit JSON in production and keep request_id on every record so
later notification_id can ride the same pipeline.
```

---

### Paso 2.4 — Request ID middleware + lifespan

**a) [`app/api/middleware/request_id.py`](app/api/middleware/request_id.py)**

Usar `starlette.middleware.base.BaseHTTPMiddleware` (suficiente en v1; no escribir un ASGI a mano salvo que ya lo dominéis).

```python
# Contrato de comportamiento, no hace falta copiar línea a línea:
# - header de entrada: X-Request-ID (si viene no vacío, usarlo; si no, uuid4)
# - request_id_ctx.set(valor) ANTES de call_next
# - try/finally con reset del token del ContextVar (no filtrar request_ids entre requests)
# - response.headers["X-Request-ID"] = valor
```

No loguear a INFO aquí.

**b) [`app/main.py`](app/main.py)**

- `lifespan` async contextmanager:
  - startup: `settings = get_settings()`; `configure_logging(settings)`; `logging.getLogger("app").info("application_started", extra={"environment": settings.environment})`
  - yield
  - shutdown: `logging.getLogger("app").info("application_stopped")` (opcional pero simétrico)
- `FastAPI(..., lifespan=lifespan)`
- `application.add_middleware(RequestIdMiddleware)` **antes** de incluir routers (en Starlette, `add_middleware` envuelve por fuera).
- Seguir incluyendo solo `health_router`.
- `app = create_app()` al final, igual que ahora.

**c) [`tests/integration/test_request_id.py`](tests/integration/test_request_id.py)**

1. `test_health_echoes_generated_request_id(client)`: `GET /health` sin header → 200, header `X-Request-ID` presente y no vacío.
2. `test_health_preserves_incoming_request_id(client)`: `GET /health` con `headers={"X-Request-ID": "client-trace-1"}` → el response header es exactamente `client-trace-1`.

`test_health_returns_ok` no se modifica (payload intacto).

- [ ] Lifespan no usa `on_event`
- [ ] Header round-trip cubierto
- **Commit (si EsrgaN autoriza):**

```text
feat: correlate logs and responses with X-Request-ID

Propagate a request id through a ContextVar so health (and later
send) can be traced without logging secrets.
```

---

### Paso 2.5 — README

Editar [`README.md`](README.md):

- Decir que **hace falta** `SECRET_KEY` (≥16) en `.env` para arrancar.
- Setup: `cp .env.example .env` antes de `uvicorn`.
- Mencionar `X-Request-ID` (opcional en curl):

```bash
cp .env.example .env
uvicorn app.main:app --reload --port 8000
curl -i http://127.0.0.1:8000/health
curl -i -H 'X-Request-ID: demo-1' http://127.0.0.1:8000/health
```

- Seguir diciendo que Docker / Postgres / Redis no son de esta fase.
- Actualizar la línea de “Phase 1 status” a **Phase 2**: health + fail-fast secret + structured logging.

No copiar `AGENTS.md`.

- [ ] Un extraño con `.env.example` puede arrancar
- **Commit (si EsrgaN autoriza):**

```text
docs: require SECRET_KEY in the local runbook

Document fail-fast boot and request-id headers without implying
Compose is ready.
```

---

## 4. Checklist de cierre de la Fase 2

- [ ] `pytest -q` verde (health + config + logging + request id)
- [ ] `ruff check app tests` limpio
- [ ] Sin `SECRET_KEY`, `Settings(_env_file=None)` explota; con él, uvicorn arranca
- [ ] `GET /health` sigue `{"status":"ok"}` y lleva `X-Request-ID`
- [ ] Cero menciones de `secret_key` en líneas de log de los tests JSON
- [ ] Cero deps nuevas en `pyproject.toml`
- [ ] Cero Dockerfile / Alembic / Celery / SQLAlchemy
- [ ] README actualizado
- [ ] 3–6 learning points en español para EsrgaN
- [ ] Commits de 2.1–2.5 hechos **o** mensajes propuestos esperando autorización

**Prohibido al “terminar”:** modelos, `POST /send`, `brew install redis`, `celery`, `alembic init`, Docker.

---

## 5. Qué pasa después (no implementar)

Cuando EsrgaN cierre esta fase, se **reemplaza** este `PLAN.md`. La siguiente pieza natural en `AGENTS.md` §10.1 es el **dominio**: enums de canal/estado, máquina de transiciones, excepciones, tests unitarios — todavía sin Postgres.

No fusionar a `main` ni pushear a menos que EsrgaN lo pida.
