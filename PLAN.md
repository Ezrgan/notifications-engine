# PLAN.md — Fase 4: Persistencia (SQLAlchemy 2 Mapped + Alembic + Postgres local)

> **REGLA OBLIGATORIA PARA TODOS LOS AGENTES:**
> Antes de ejecutar cualquier paso, leer y acatar [`AGENTS.md`](./AGENTS.md), [`.cursor/rules/`](./.cursor/rules/) (sobre todo `postgresql.mdc` y `testing.mdc`) y [`docs/HOW_TO_WRITE_THE_NEXT_PLAN.md`](./docs/HOW_TO_WRITE_THE_NEXT_PLAN.md).
> Este archivo es el **único plan ejecutable**. Describe **una sola fase**. Cuando cierre, EsrgaN **reescribe** `PLAN.md` entero (ver el playbook en `docs/`).
> No implementar `POST /send`, auth `X-API-Key`, hash de keys, Redis, Token Bucket, Celery, providers, métricas, mapper HTTP de excepciones ni Docker.

> **Cómo está pensado este documento:**
> Un agente debe poder implementarlo **sin inventar**. Cada paso: archivos exactos, contrato, tests, commit propuesto, qué no tocar.
> Código completo. Cero placeholders. Cero `# ... rest of code ...`.
> Enseñar a EsrgaN en **español simple**, con ejemplos. Sin jerga sin definir.

> **Estado de partida (verificado en `main`, commit `9a57e86`):**
> Fase 3 **cerrada y mergeada** (PR #4). `pytest -q` → **27 passed**. `ruff check app tests` limpio.
> Hay dominio (`Channel`, `NotificationStatus`, máquina de transiciones). `app/models/__init__.py` solo tiene un docstring. **No** existe `alembic.ini` ni `alembic/`. `pyproject.toml` **no** lista SQLAlchemy/Alembic/psycopg. Settings **no** exige `DATABASE_URL`. `GET /health` → 200 `{"status":"ok"}` sin I/O. Homebrew `psql (PostgreSQL) 14.19` está instalado. Cero Dockerfile.

---

## 0. Decisiones congeladas (esta fase)

| # | Decisión | Valor congelado |
| --- | --- | --- |
| D1 | Idea de la fase | Tablas reales en Postgres **local** (Homebrew 14.x). El dominio ya dice qué estados existen; ahora la BD los **guarda**. Cero envío, cero cola. |
| D2 | Postgres | **14.x Homebrew**, `localhost:5432`. Ya está `14.19` en esta máquina. `.cursor/rules/postgresql.mdc` menciona 16: **gana `AGENTS.md`** (14+ / Homebrew 14). No actualizar a 16. No Docker. |
| D3 | Bases | App: `notifications_engine`. Tests: `notifications_engine_test`. Nunca mezclar. Crearlas con `createdb` si no existen. |
| D4 | Driver | `psycopg` v3 (paquete `psycopg[binary]`). URL **obligatoria** con prefijo `postgresql+psycopg://`. Rechazar `postgresql://`, `postgres://`, SQLite. |
| D5 | ORM | SQLAlchemy **2.0** estilo `Mapped[]` / `mapped_column`. `DeclarativeBase` en `app/models/base.py`. **Prohibido** `create_all` en app, tests y scripts. **Prohibido** SQLAlchemy 1.4 `Query`. |
| D6 | Migraciones | **Alembic only**. `alembic.ini` + `alembic/`. Una revisión que crea `clients` y `notifications`. `env.py` toma la URL de `Settings`, no de un string hardcodeado. |
| D7 | Engine / Session | **Síncronos** (`Engine` + `Session`). `pool_pre_ping=True`. Creados en el **lifespan** de FastAPI; `engine.dispose()` al apagar. Guardar `engine` y `session_factory` en `app.state`. No `AsyncSession`, no `asyncpg`. |
| D8 | Settings | `database_url: SecretStr` **obligatorio** (fail-fast, como `SECRET_KEY`). Validador: el valor debe empezar por `postgresql+psycopg://`. **No** default a un socket local oculto. `REDIS_URL` sigue **ausente**. |
| D9 | Health | `GET /health` **no** abre sesión ni hace `SELECT 1`. Si Postgres está caído, health sigue 200. Liveness ≠ readiness. |
| D10 | Tablas | Las **dos**: `clients` y `notifications`. `notifications.client_id` es FK a `clients.id` con `ON DELETE RESTRICT`. Auth HTTP (`X-API-Key`, hash helpers) es **Fase 5**; aquí solo existe la columna `hashed_api_key` (los tests insertan un string dummy). |
| D11 | IDs y tiempo | PK `UUID` (default Python `uuid.uuid4`). Timestamps `DateTime(timezone=True)` / `TIMESTAMPTZ`. `created_at` / `updated_at` NOT NULL. `sent_at` nullable. |
| D12 | Enums en columnas | Reusar `app.domain.enums.Channel` y `NotificationStatus`. SQLAlchemy `Enum(..., native_enum=False)` → **VARCHAR**, no tipo `ENUM` de Postgres (ALTER TYPE duele). El dominio sigue sin importar SQLAlchemy. |
| D13 | JSON | `payload` = `JSONB` NOT NULL, default Python `dict` (no `default={}`). |
| D14 | Idempotencia en BD | Índice único **parcial**: `(client_id, idempotency_key) WHERE idempotency_key IS NOT NULL`. Varias filas del mismo cliente con `idempotency_key` NULL **sí** se permiten. La política HTTP de replay es Fase 6. |
| D15 | Repositorios / deps | **No** crear `NotificationRepository` ni `app/api/deps.py`. Los tests de persistencia usan `Session` de `session_factory`. El `Depends(get_db)` llega cuando un router de producto lo necesite. |
| D16 | Tests | Unitarios de Settings **sin** Postgres. Persistencia = `tests/integration/test_persistence.py` contra Postgres **real** + `alembic upgrade` (no SQLite, no `create_all`, no `time.sleep`). Domain tests siguen sin importar SQLAlchemy. |
| D17 | Git | Rama `feat/phase-4-persistence` desde `main` (`9a57e86`). Commits **solo si EsrgaN lo pide**. |
| D18 | Docker / extras | Prohibidos. No Kafka, JWT, Prisma, Redis, Celery. No libs que `AGENTS.md` no nombre. |
| D19 | Docs | `README.md`: Postgres local + `alembic upgrade head`. `docs/STATUS.md` se actualiza **al final** de la implementación (no en este turno de escritura del PLAN). |

### Columnas congeladas

**`clients`**

| Columna | Tipo ORM | Restricciones |
| --- | --- | --- |
| `id` | `UUID` | PK, `default=uuid.uuid4` |
| `name` | `String(128)` | NOT NULL |
| `hashed_api_key` | `String(255)` | NOT NULL, UNIQUE. Cero key en claro. |
| `is_active` | `bool` | NOT NULL, default `True` |
| `rate_limit_per_minute` | `int \| None` | NULL = “usar el default global más adelante (10/min)”. No añadir ese default a Settings ahora. |
| `created_at` | `DateTime(timezone=True)` | NOT NULL, `server_default=func.now()` |
| `updated_at` | `DateTime(timezone=True)` | NOT NULL, `server_default=func.now()`, `onupdate=func.now()` |

**`notifications`**

| Columna | Tipo ORM | Restricciones |
| --- | --- | --- |
| `id` | `UUID` | PK, `default=uuid.uuid4` |
| `client_id` | `UUID` | FK `clients.id`, `ON DELETE RESTRICT`, NOT NULL, index |
| `channel` | enum dominio → VARCHAR | NOT NULL |
| `recipient` | `String(320)` | NOT NULL (sin validar email/teléfono) |
| `template` | `String(128)` | NOT NULL (identificador, no un CMS) |
| `payload` | `JSONB` | NOT NULL |
| `status` | enum dominio → VARCHAR | NOT NULL, default `PENDING` |
| `retry_count` | `int` | NOT NULL, default `0` |
| `idempotency_key` | `String(128) \| None` | nullable; único **por cliente cuando está presente** (D14) |
| `error_message` | `Text \| None` | nullable |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | igual que clients |
| `sent_at` | `DateTime(timezone=True) \| None` | nullable |

Relación ORM: `Client.notifications` / `Notification.client`. `back_populates`. No cascada de delete.

---

## 1. Diagnóstico (por qué esta fase)

Archivos reales, no memoria:

1. [`docs/STATUS.md`](docs/STATUS.md) marca Fases 1–3 hechas. [`AGENTS.md`](AGENTS.md) §10.1 siguiente número libre = **4 Persistencia**. No saltar a `/send` (fase 6): sin tabla, el 202 no tendría `notification_id` durable.
2. [`app/domain/enums.py`](app/domain/enums.py) y [`app/domain/state_machine.py`](app/domain/state_machine.py) ya cierran canales y transiciones. Si la columna `status` nace como `String` libre, un `UPDATE` podría guardar `SENT → PENDING` sin pasar por el dominio. El ORM reusa esos enums; **no** reimplementa la máquina (la máquina sigue siendo funciones puras).
3. [`app/models/__init__.py`](app/models/__init__.py) está vacío. [`app/core/config.py`](app/core/config.py) dice a propósito que `DATABASE_URL` no existe todavía. Esta fase **abre** la conexión: ahora sí es obligatorio (playbook §3).
4. [`app/api/routers/health.py`](app/api/routers/health.py) no hace I/O. Debe seguir así: un probe de “¿el proceso vive?” no debe fallar porque Postgres esté reiniciando.
5. [`pyproject.toml`](pyproject.toml) no tiene SQLAlchemy. Hay que **añadir e instalar** deps; no asumir que ya están.
6. Ejemplo de uso: insertas un cliente “checkout-app” y una notificación `PENDING` a `user@example.com`. Reinicias Uvicorn. La fila sigue ahí. Eso es persistencia. `/send` todavía no existe; lo harás a mano en un test, no con curl de producto.

---

## 2. Árbol al cerrar esta fase

```text
pyproject.toml                          # EDITAR: sqlalchemy, alembic, psycopg[binary]
.env.example                            # EDITAR: DATABASE_URL descomentada, placeholder
alembic.ini                             # NUEVO (alembic init)
alembic/
  env.py                                # NUEVO + EDITAR URL/metadata
  script.py.mako                        # NUEVO (lo genera alembic init)
  versions/
    <rev>_create_clients_and_notifications.py   # NUEVO
app/core/config.py                      # EDITAR: database_url obligatorio
app/core/db.py                          # NUEVO: engine + session_factory
app/main.py                             # EDITAR: lifespan crea/dispose engine
app/models/__init__.py                  # EDITAR: reexportar Base, Client, Notification
app/models/base.py                      # NUEVO
app/models/client.py                    # NUEVO
app/models/notification.py              # NUEVO
tests/conftest.py                       # EDITAR: DATABASE_URL de test antes de importar app
tests/unit/test_config.py               # EDITAR: fail-fast DATABASE_URL + prefix
tests/unit/test_logging.py              # EDITAR: setenv DATABASE_URL en los Settings() válidos
tests/integration/test_persistence.py   # NUEVO
tests/integration/conftest.py           # NUEVO: engine, alembic upgrade, session con rollback
README.md                               # EDITAR: Postgres + alembic
docs/STATUS.md                          # EDITAR en el último paso de implementación
```

**No crear:** `app/api/deps.py`, repositorios, `app/core/security.py`, routers de `/api/v1/`, `Dockerfile`, `docker-compose.yml`, nada en `app/domain/` (el dominio no cambia).

**No tocar:** máquina de estados, health payload, `SECRET_KEY` (sigue obligatorio).

---

## 3. Git

```bash
git checkout main
git pull   # si aplica; HEAD esperado 9a57e86
git checkout -b feat/phase-4-persistence
```

Antes de cerrar cada paso de código:

```bash
source .venv/bin/activate
pytest -q
ruff check app tests
```

Los 27 tests de Fases 2–3 deben seguir verdes (más los nuevos de esta fase).

---

## FASE 0 — Preparación

- [ ] `pytest -q` → 27 passed (o más, todos verdes) **antes** de editar
- [ ] `ruff check app tests` limpio
- [ ] `psql --version` muestra 14.x (Homebrew). No instalar Postgres 16.
- [ ] Postgres acepta conexiones locales:

```bash
createdb notifications_engine 2>/dev/null || true
createdb notifications_engine_test 2>/dev/null || true
psql -d notifications_engine -c 'SELECT 1'
psql -d notifications_engine_test -c 'SELECT 1'
```

Si `createdb` pide usuario, usar el de macOS (en esta máquina: peer/trust típico de Homebrew). Documentar la URL real en `.env` **local** (gitignored), no en el repo.

- [ ] Rama `feat/phase-4-persistence` creada
- [ ] Cero Docker, cero Compose
- [ ] Enseñar a EsrgaN (ejemplo): `createdb` es “crea una base vacía con este nombre”. Todavía no hay tablas; Alembic las pondrá. Es como tener una carpeta vacía antes de crear archivos.

---

## FASE 4 — Persistencia

### Paso 4.1 — Dependencias

Editar [`pyproject.toml`](pyproject.toml). Añadir a `dependencies` (mismo estilo de pines que FastAPI):

```toml
"sqlalchemy>=2.0.36,<3",
"alembic>=1.14,<2",
"psycopg[binary]>=3.2,<4",
```

Instalar en el venv:

```bash
source .venv/bin/activate
uv pip install -e ".[dev]"
```

No añadir `asyncpg`, `psycopg2`, `prisma`, `sqlmodel`.

- **Patrón:** pin de dependencias de runtime (la app las necesita para hablar con Postgres).
- **Por qué:** sin el driver, SQLAlchemy no abre sockets a Postgres. `psycopg[binary]` trae la lib compilada; no hace falta `brew install libpq` extra para el alumno.
- **Alternativa descartada:** `psycopg2-binary` (driver viejo). SQLAlchemy 2 + Python 3.12 prefieren psycopg 3. El `.env.example` ya comentaba `postgresql+psycopg://`.
- **Capa:** empaquetado (`pyproject.toml`), no dominio.

Cero tests nuevos en este paso salvo que `pytest -q` siga en 27.

- **Commit (si EsrgaN autoriza):**

```text
chore: add SQLAlchemy, Alembic, and psycopg

Persistence needs a 2.0 ORM, migration history, and a Postgres
driver before any table or session code can run.
```

---

### Paso 4.2 — `DATABASE_URL` fail-fast

Editar [`app/core/config.py`](app/core/config.py):

- Campo `database_url: SecretStr` obligatorio (`Field(min_length=1)`).
- Validador: `get_secret_value()` debe empezar por `postgresql+psycopg://`. Si no, `ValueError` (Pydantic lo envuelve en `ValidationError`).
- Actualizar el docstring del módulo: ya no digas que `DATABASE_URL` está ausente; `REDIS_URL` sigue ausente.
- **No** default. **No** leer un hostname mágico.

Editar [`.env.example`](.env.example): descomentar y dejar placeholder (sin password real):

```text
DATABASE_URL=postgresql+psycopg://USER@localhost:5432/notifications_engine
```

Quitar el comentario “Unused until later…” de esa línea. `REDIS_URL` sigue comentada.

Editar [`tests/conftest.py`](tests/conftest.py): **antes** de `from app.main import create_app`, forzar la URL de **test** (no la de desarrollo):

```python
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://localhost:5432/notifications_engine_test",
)
os.environ.setdefault("SECRET_KEY", "pytest-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")
```

Si el usuario sin password falla, `TEST_DATABASE_URL` permite `postgresql+psycopg://USER@localhost:5432/notifications_engine_test` sin tocar código.

Editar [`tests/unit/test_config.py`](tests/unit/test_config.py):

- En **todo** `Settings()` que hoy solo pone `SECRET_KEY` y debe **pasar**, añadir `monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost:5432/notifications_engine_test")`.
- Tests nuevos:
  1. Sin `DATABASE_URL` → `ValidationError` (borrar env + `_env_file=None`).
  2. `DATABASE_URL=postgresql://localhost/db` (sin `+psycopg`) → `ValidationError`.
  3. `SECRET_KEY` corto sigue fallando (regresión).

Editar [`tests/unit/test_logging.py`](tests/unit/test_logging.py): mismo `setenv` de `DATABASE_URL` en los tres tests que construyen `Settings()`.

`GET /health` debe seguir 200 (aún no hay engine; si este paso se mergea solo, Settings ya exige la URL y el TestClient del conftest la tiene).

- **Patrón:** fail-fast configuration (`pydantic-settings`).
- **Por qué en este servicio:** un API que “arranca” sin saber dónde está Postgres aceptaría trabajo que no puede guardar. Ejemplo: olvidas `.env` → el proceso **muere al boot** con error claro, no a las 3 a.m. en el primer insert.
- **Alternativa descartada:** default `postgresql+psycopg://localhost/...` (AGENTS.md lo prohíbe: socket oculto que solo funciona en una máquina).
- **Capa:** `app/core/` (config). El dominio no sabe qué es una URL.

- **Commit (si EsrgaN autoriza):**

```text
feat: require DATABASE_URL before the app boots

Fail fast with a psycopg URL so a misconfigured process cannot
pretend it can persist notifications.
```

---

### Paso 4.3 — Modelos Mapped

Crear [`app/models/base.py`](app/models/base.py):

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative metadata root. Alembic uses Base.metadata."""
```

Crear [`app/models/client.py`](app/models/client.py) y [`app/models/notification.py`](app/models/notification.py) con **exactamente** las columnas de D10–D14 y la tabla de §0.

Contrato mínimo de `Notification` (el agente completa imports y `Client` igual de explícito):

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import Channel, NotificationStatus
from app.models.base import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "uq_notifications_client_idempotency",
            "client_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel: Mapped[Channel] = mapped_column(
        Enum(Channel, values_callable=lambda members: [m.value for m in members], native_enum=False, length=16),
        nullable=False,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(
            NotificationStatus,
            values_callable=lambda members: [m.value for m in members],
            native_enum=False,
            length=16,
        ),
        nullable=False,
        default=NotificationStatus.PENDING,
    )
    # recipient, template, payload, retry_count, idempotency_key, error_message,
    # created_at, updated_at, sent_at: seguir la tabla congelada
    client: Mapped["Client"] = relationship(back_populates="notifications")
```

Usar `UUID(as_uuid=True)` de `sqlalchemy.dialects.postgresql` **o** `sqlalchemy.Uuid` 2.0; una sola forma en los dos modelos, no mezclar.

Editar [`app/models/__init__.py`](app/models/__init__.py): importar `Base`, `Client`, `Notification` para que `Base.metadata` vea ambas tablas. `__all__` explícito. Quitar el docstring “Empty in phase 1”.

**Prohibido en los modelos:** métodos `mark_sent()` / llamar a `transition()`. Eso es dominio + servicio, no ORM. El modelo es un documento de columnas.

`app/domain/` no importa `app.models`.

- **Patrón:** Active Record ligero / mapping ORM (unidad: una clase = una tabla). Capa **persistencia**.
- **Por qué:** el worker y el API (más adelante) hablan Python (`notification.status is NotificationStatus.PENDING`), no strings mágicos `"pending"` vs `"PENDING"`.
- **Alternativa descartada:** tipo `ENUM` nativo de Postgres. Añadir un valor nuevo exige `ALTER TYPE` y Alembic se pelea. VARCHAR + enum Python es suficiente a esta escala (miles/día).
- **Otra alternativa descartada:** SQLite “mientras tanto”. JSON/UUID/índice parcial no se comportan igual.

Tests en este paso: ninguno que necesite Postgres todavía (llegan en 4.6). `pytest -q` de lo existente sigue verde. `ruff` / imports OK.

- **Commit (si EsrgaN autoriza):**

```text
feat: map clients and notifications with SQLAlchemy 2

Give Postgres a schema that reuses domain Channel and
NotificationStatus instead of free-form status strings.
```

---

### Paso 4.4 — Engine, session factory, lifespan

Crear [`app/core/db.py`](app/core/db.py). Responsabilidad única: construir engine y `sessionmaker`. Quién lo llama: lifespan (y tests de persistencia). Nadie más crea `create_engine` por su cuenta.

```python
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_engine_from_url(database_url: str) -> Engine:
    """Build a sync engine. pool_pre_ping survives a local Postgres restart."""
    return create_engine(database_url, pool_pre_ping=True, echo=False)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a factory of short-lived sessions. Callers close or use context managers."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
```

`autoflush=False` + commit explícito: más adelante el *use case* (servicio) hace commit a propósito, no un helper escondido (AGENTS.md §6.4). `expire_on_commit=False` evita lazy-load sorpresa al devolver el objeto después del commit en tests.

Editar [`app/main.py`](app/main.py) lifespan:

1. `configure_logging` como ahora.
2. `engine = create_engine_from_url(settings.database_url.get_secret_value())`.
3. `application.state.engine = engine`.
4. `application.state.session_factory = create_session_factory(engine)`.
5. `yield`.
6. `engine.dispose()` y log `application_stopped`.

Renombrar el parámetro `_application` a `application` (ahora sí se usa).

**No** hacer `engine.connect()` ni `SELECT 1` al arrancar (D9). `create_engine` es perezoso: no habla con Postgres hasta el primer checkout del pool.

**No** crear `get_db` en routers. Health no cambia.

Tests: `test_health_returns_ok` y request-id siguen verdes. Lifespan ahora construye engine (sin conectar). Si la URL es válida en forma, no hace falta Postgres para `/health`.

- **Patrón:** composition root (fábrica de la app posee el engine). Dependency injection a través de `app.state`, no `create_engine()` dentro de un endpoint.
- **Por qué:** dos requests no deben abrir cada uno su propio pool. Ejemplo: 100 requests → un pool, muchas `Session` cortas.
- **Alternativa descartada:** `AsyncSession` + `asyncpg`. El worker Celery (fase 9) es sync; dos stacks async/sync enseñan peor y no ganan nada a miles/día.
- **Capa:** `app/core/` + `app/main.py`. Los modelos no crean el engine.

- **Commit (si EsrgaN autoriza):**

```text
feat: open a request-scoped Postgres session factory at startup

Own the engine in the app lifespan so endpoints never construct
their own connections.
```

---

### Paso 4.5 — Alembic

Desde la raíz del repo, con venv activo y deps instaladas:

```bash
alembic init alembic
```

Eso crea `alembic.ini` y `alembic/`. **No** commitear una URL con password en `alembic.ini`. Dejar `sqlalchemy.url =` vacío o un placeholder; `env.py` lo pisa.

Editar [`alembic/env.py`](alembic/env.py):

- Importar `get_settings`, `Base`, y los modelos (`from app.models import Base, Client, Notification`) para registrar tablas en `metadata`.
- `target_metadata = Base.metadata`.
- `config.set_main_option("sqlalchemy.url", get_settings().database_url.get_secret_value())`.
- Conservar `run_migrations_offline` / `run_migrations_online` que genera Alembic; no reescribir el archivo de cero si no hace falta.

Alembic necesita `SECRET_KEY` + `DATABASE_URL` porque usa `Settings`. Documentar: tener `.env` copiado (dev apunta a `notifications_engine`, no a `_test`).

Generar la revisión:

```bash
alembic revision --autogenerate -m "create clients and notifications"
```

**Revisar el archivo en `alembic/versions/` a mano.** Autogenerate es un borrador, no verdad:

- Debe crear `clients` y `notifications`.
- `payload` tipo JSONB / `postgresql.JSONB`.
- FK `client_id` → `clients.id`.
- Índice único parcial `uq_notifications_client_idempotency`. Si autogenerate **no** lo emitió, **añadirlo a mano** en `upgrade()` y el `drop_index` en `downgrade()`.
- Cero `ENUM` nativo de Postgres.
- `downgrade()` hace drop de índices y tablas (notifications primero, luego clients).

Aplicar en **dev**:

```bash
alembic upgrade head
```

Comprobar:

```bash
psql -d notifications_engine -c '\dt'
psql -d notifications_engine -c '\d notifications'
```

Debe haber exactamente esas dos tablas de producto (más `alembic_version`).

- **Patrón:** migraciones versionadas (historia del esquema).
- **Por qué:** ejemplo: en el portátil de EsrgaN y más adelante en Compose, `alembic upgrade head` deja el mismo esquema. `create_all` no guarda el “cómo llegamos aquí” y se desvía entre máquinas.
- **Alternativa descartada:** `Base.metadata.create_all(engine)` en el lifespan. AGENTS.md lo trata como defecto, no como atajo de desarrollo.
- **Capa:** `alembic/` (infra). Los modelos declaran el destino; Alembic es el camino.

No hace falta un test que parsee el archivo de revisión. El paso 4.6 **ejecuta** `upgrade` contra la BD de test: si la migración está mal, el insert falla.

- **Commit (si EsrgaN autoriza):**

```text
feat: add Alembic migration for clients and notifications

Schema changes go through revision history so local Postgres
cannot drift from a silent create_all.
```

---

### Paso 4.6 — Tests de persistencia (Postgres real)

Crear [`tests/integration/conftest.py`](tests/integration/conftest.py):

1. Fixture **session-scoped** `persistence_engine`:
   - URL = `os.environ["DATABASE_URL"]` (ya forzada al `_test` en el conftest raíz).
   - Correr Alembic: `command.upgrade(alembic_cfg, "head")` con `script_location` apuntando al `alembic/` del repo.
   - `yield engine`; al final `engine.dispose()`.
2. Fixture **function-scoped** `db_session`:
   - Abrir conexión, `connection.begin()`.
   - `Session(bind=connection)`.
   - `yield session`.
   - rollback de la transacción + close. Así cada test deja la BD limpia **sin** `TRUNCATE` a mano y **sin** `sleep`.

Si Postgres no está arriba, el test debe **fallar** con el error de conexión (mensaje claro). **No** `pytest.skip`. EsrgaN tiene que ver que esta fase exige Postgres local. **No** SQLite.

Crear [`tests/integration/test_persistence.py`](tests/integration/test_persistence.py) — **obligatorios**:

1. Insertar `Client` (name, `hashed_api_key="dummy-hash-not-a-real-key"`, `is_active=True`) + `Notification` (`channel=Channel.EMAIL`, `recipient="user@example.com"`, `template="welcome"`, `payload={"x": 1}`, `status` default). `flush` o `commit` según el fixture. Reloading: `status is NotificationStatus.PENDING`, `payload["x"] == 1`, `channel is Channel.EMAIL`.
2. Dos notificaciones del **mismo** cliente con `idempotency_key=None` → ambas se insertan (no IntegrityError).
3. Dos notificaciones del mismo cliente con el **mismo** `idempotency_key="replay-1"` → la segunda lanza `IntegrityError`.
4. `GET /health` sigue 200 `{"status":"ok"}` (regresión; no abre sesión).
5. Un test de unidad de dominio existente sigue importable: no hace falta repetirlo; `pytest tests/unit/domain -q` en el checklist basta.

**Prohibido:** `time.sleep`, Twilio, `TestClient` que inserte por `/send` (no existe), `create_all`.

Helper local en el test file para armar un `Client` (no un `helpers.py` de proyecto).

- **Patrón:** test de integración contra la BD real (el contrato que SQLite mentiría).
- **Por qué:** el índice parcial es comportamiento de **Postgres**. Ejemplo: dos SMS sin key de idempotencia deben poder existir; dos con `key=abc` no.
- **Alternativa descartada:** fakeredis-style fake de SQLAlchemy. No ejercita JSONB ni el índice.
- **Capa:** `tests/integration/`. No mockear `Notification` ni la máquina de estados.

- **Commit (si EsrgaN autoriza):**

```text
test: persist notifications against local Postgres

Prove Alembic tables, JSONB payload, and the partial
idempotency unique index without hitting the HTTP send path.
```

---

### Paso 4.7 — Docs de status + README

Editar [`docs/STATUS.md`](docs/STATUS.md) **solo al cerrar la implementación** (otro turno, o el final de este PLAN cuando el código exista):

- Marcar Fase 4 hecha: modelos, Alembic, `DATABASE_URL`, dos tablas.
- Decir qué **sigue**: Fase 5 = hash de API keys + `X-API-Key` Depends. Aún no `/send`.
- Arranque local: `alembic upgrade head` + `DATABASE_URL` en `.env`.
- “Qué no existe” sigue incluyendo send, Redis, Celery, Docker.

Editar [`README.md`](README.md):

- Prerequisites: Postgres 14 Homebrew además de Python 3.12 / `uv`.
- Setup: `createdb` de las dos bases, copiar `.env`, rellenar `DATABASE_URL`, `alembic upgrade head`.
- Una línea de status: “Phase 4: Postgres tables exist; still no `/send`”.
- Docker sigue “fase posterior”.

No copiar el DDL entero al README.

- **Commit (si EsrgaN autoriza):**

```text
docs: record local Postgres and Alembic in project status
```

---

## 4. Checklist de cierre

- [ ] `pytest -q` verde (27 anteriores + config DATABASE_URL + persistencia)
- [ ] `ruff check app tests` limpio
- [ ] `app/domain/` sigue sin importar SQLAlchemy/FastAPI
- [ ] Cero `create_all` en código de app o tests
- [ ] `alembic upgrade head` aplicado en `notifications_engine` local
- [ ] `GET /health` no consulta Postgres
- [ ] Cero routers `/api/v1/`, cero Redis, cero Celery, cero Docker, cero hash/verify de API keys
- [ ] 3–6 learning points en español **simple** para EsrgaN (qué es un ORM, qué es una migración, ejemplo FK RESTRICT, por qué VARCHAR y no ENUM de PG, por qué health no hace `SELECT 1`)
- [ ] Commits hechos o mensajes esperando a EsrgaN

**Prohibido al terminar:** `POST /send`, `X-API-Key`, Celery, Redis, `BackgroundTasks`, JWT, Compose.

---

## 5. Qué sigue (no implementar)

Siguiente `PLAN.md` (otra reescritura): **API keys** — hash de la key en reposo + FastAPI `Depends` que lee `X-API-Key` y carga el `Client`. Todavía no hay cola ni `POST /send`.
