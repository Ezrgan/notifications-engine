# PLAN.md — Fase 9: Celery worker en el mismo venv + provider simulado

> **REGLA OBLIGATORIA PARA TODOS LOS AGENTES:**
> Antes de ejecutar cualquier paso, leer y acatar [`AGENTS.md`](./AGENTS.md), [`.cursor/rules/`](./.cursor/rules/) (sobre todo `celery.mdc`, `fastapi.mdc`, `testing.mdc` y `anti-overengineering.mdc`) y [`docs/HOW_TO_WRITE_THE_NEXT_PLAN.md`](./docs/HOW_TO_WRITE_THE_NEXT_PLAN.md).
> Este archivo es el **único plan ejecutable**. Describe **una sola fase**. Cuando cierre, EsrgaN **reescribe** `PLAN.md` entero (ver el playbook en `docs/`).
> No implementar retries, DLQ, Beat, JWT, alta HTTP de clientes, Prometheus, Mailtrap/Twilio reales ni Docker.

> **Cómo está pensado este documento:**
> Un agente debe poder implementarlo **sin inventar**. Cada paso: archivos exactos, contrato, tests, commit propuesto, qué no tocar.
> Código completo. Cero placeholders. Cero `# ... rest of code ...`.
> Enseñar a EsrgaN en **español simple**, con ejemplos. Sin jerga sin definir.

> **Estado de partida (verificado):**
> Rama actual `feat/phase-8-token-bucket` = `ea4da85` (mismo árbol que `origin/main` = `03c28d6`, PR **#9**).
> `main` local = `7a2b828` — **atrás**; no partir de `main` local. Partir de `origin/main` (`03c28d6`) o de `feat/phase-8-token-bucket` (`ea4da85`).
> `pytest -q` → **90 passed**. `ruff check app tests` limpio. `redis-cli ping` → `PONG`. Paquete `celery` **no** está en el venv.
> Hay `POST /send` → 202 + `PENDING` + cola **in-memory**, Token Bucket Redis índice **0**, `GET …/status`, `GET /metrics`.
> `app/workers/__init__.py` y `app/providers/__init__.py` existen como stubs vacíos. **No** hay `celery_app.py`, `tasks.py`, puerto de provider ni `DispatchService`.
> `pyproject.toml` no lista `celery`. Settings no tiene `CELERY_BROKER_URL`.

---

## 0. Decisiones congeladas (esta fase)

| # | Decisión | Valor congelado |
| --- | --- | --- |
| D1 | Idea de la fase | El mostrador (`POST /send`) **sigue sin enviar**. Guarda `PENDING`, pone el id en la cola y responde **202**. Un **segundo proceso** en el **mismo venv** (`celery worker`) toma ese id, pasa `PENDING → PROCESSING`, llama al provider **simulado**, pasa `PROCESSING → SENT`. Ejemplo: el checkout cobra y recibe `202` en 20 ms; el email “sale” (simulado) unos segundos después, cuando el worker está vivo. |
| D2 | Celery es un paquete | `celery[redis]` se instala en el venv con `uv pip`. **No** es una imagen Docker. Ejemplo: terminal 1 `uvicorn …`, terminal 2 `celery -A app.workers.celery_app worker …`. Dos procesos Python, cero Compose. |
| D3 | Broker ≠ cubo | Token Bucket sigue en `REDIS_URL` = `redis://localhost:6379/0`. Celery usa **otro índice** del **mismo** Redis: `CELERY_BROKER_URL` = `redis://localhost:6379/1`. Ejemplo: las fichas del torniquete no se mezclan con los tickets de cocina. Prohibido reutilizar `/0` como broker. Prohibido un segundo `redis-server`. |
| D4 | Settings | `celery_broker_url: SecretStr` **obligatorio**, prefijo `redis://`. Sin `CELERY_BROKER_URL` el proceso **no arranca** (fail-fast, igual que `REDIS_URL`). Tests HTTP no hablan con el broker (D12); igual deben setear la variable. |
| D5 | Puerto de cola | El Protocol `NotificationQueue` **no se toca**. Nuevo adapter `CeleryNotificationQueue.enqueue(id)` → `deliver_notification.apply_async(args=[str(id)], queue="notifications")`. `InMemoryNotificationQueue` **sigue** para `ENVIRONMENT=test`. `NotificationService.accept` **no cambia**. |
| D6 | Payload de la task | Solo el UUID en **string**. Prohibido pasar el modelo ORM, el body HTTP o el API key. Ejemplo: el ticket dice “pedido 42”, no “el plato caliente en la bandeja”. El worker **carga** la fila desde Postgres. |
| D7 | Cola nombrada | Queue Kombu **`notifications`**. No dejar el default `celery` (ese nombre no enseña nada). `task_ignore_result=True`: la verdad está en Postgres, no en un result backend. Serializer **JSON** (no pickle). `task_acks_late=True`, `worker_prefetch_multiplier=1`. |
| D8 | Cero retries / DLQ | `@task(..., max_retries=0)`. **No** countdowns 5s/15s/45s. **No** cola `notifications.dlq`. **No** Celery Beat. Eso es Fase 10. Si el provider simulado funciona, la fila acaba `SENT`. |
| D9 | Provider = puerto + simulado | Protocol `NotificationProvider.send(message)` en `app/providers/port.py`. Adapter `SimulatedNotificationProvider` en `app/providers/simulated.py`: log + return, **cero** red. Un solo adapter para email/sms/push/webhook. Prohibido `import twilio` / Mailtrap. La política de reintento **no** vive en el adapter. |
| D10 | Caso de uso dispatch | `DispatchService` en `app/services/dispatch.py`. El worker lo llama; los routers **no**. Usa `assert_transition` del dominio (nunca un `row.status = SENT` a pelo desde `PENDING`). El servicio **posee** el `commit`, igual que `accept`. |
| D11 | Máquina de estados | `PENDING → PROCESSING` (commit) → `provider.send` → `PROCESSING → SENT` + `sent_at` (commit). Si ya es `SENT` o `FAILED`, **no** llamar al provider (no doble envío). Si ya es `PROCESSING` (worker murió a mitad), reintentar el send (recuperación). `PENDING → SENT` es **ilegal**: hay que persistir `PROCESSING`. Missing id → log y return, no crash infinito. |
| D12 | Tests vs local | `ENVIRONMENT=test` → lifespan **sigue** `InMemoryNotificationQueue` (los 90 tests de 202/`PENDING` no arrancan un worker). `local` / `production` → `CeleryNotificationQueue`. Pytest **no** exige `celery worker` vivo. Cero `time.sleep`. Cero `task_always_eager` en el fixture HTTP (rompería `test_send_returns_202_pending_*`). |
| D13 | Fallo del provider (esta fase) | `ProviderError` → `PROCESSING → FAILED` + `error_message` (truncado a 512), commit, la task **termina** (no re-raise). El simulado **nunca** lanza. Fase 10 sustituirá este FAILED inmediato por backoff + DLQ. Otras excepciones del provider: también `FAILED` (un solo `except ProviderError` no basta — captura `Exception` **después** de persistir PROCESSING, log `exc_info`, marca FAILED). No `except: pass`. |
| D14 | Broker caído en `enqueue` | `CeleryNotificationQueue` lanza `QueueUnavailableError`. El handler HTTP **503** `queue unavailable` **ya existe**. La fila `PENDING` **sí** queda (igual que hoy: commit primero, luego enqueue). No inventes un rollback del persist. |
| D15 | Repositorio | Nuevo `NotificationRepository.get_by_id(id)` (PK, sin filtrar `client_id`). El worker es interno. **No** uses `get_by_id_for_client` aquí. **No** abras un GET HTTP público “por id sin auth”. Cero Alembic: `sent_at` y `error_message` ya existen. |
| D16 | Composition root del worker | El worker **no** llama `create_app()`. Engine + session factory en `app/workers/runtime.py` (lazy singleton). Task: abre sesión, construye `DispatchService` + `SimulatedNotificationProvider`, `dispatch`, cierra sesión. Prohibido importar `app.api.routers`. |
| D17 | HTTP intacto | Routers, Token Bucket, auth, metrics, health: **no cambian de contrato**. `POST /send` sigue 202 `PENDING`. `GET /status` ya admite `PROCESSING`/`SENT` (el enum ya está). `GET /metrics` pasará a `sent: 1` **después** de que el worker marque `SENT` — no en el mismo request. |
| D18 | Libs | `celery[redis]>=5.4,<6` en **dependencies** (el API también llama `apply_async`). Prohibido `flower`, `celery-redbeat`, `twilio`, `httpx` de más, `BackgroundTasks`, JWT, `kombu` extra a mano (ya viene con Celery). |
| D19 | Logs | Eventos: `notification_dispatch_started`, `notification_sent`, `notification_dispatch_skipped`, `notification_dispatch_failed`, `notification_dispatch_missing`, `simulated_send`. `extra=` con `notification_id`, `client_id`, `channel`, `status`, `retry_count`. Nunca API key ni payload completo. |
| D20 | Fuera de esta fase | Retries, DLQ, Beat, mapper HTTP de `InvalidStatusTransition`, `ClientService`, cablear `Client.rate_limit_per_minute`, Mailtrap/Twilio, Dockerfile/Compose, eager por defecto, result backend Redis. |
| D21 | Git | Rama `feat/phase-9-celery-worker` **desde** `origin/main` (`03c28d6`) o `feat/phase-8-token-bucket` (`ea4da85`) — mismo árbol. **No** desde `main` local (`7a2b828`). Commits **solo si EsrgaN lo pide**. |
| D22 | Docker / extras | Prohibidos. No Kafka, JWT, Prisma, Compose, segundo Redis. |

---

## 1. Diagnóstico (por qué esta fase)

Archivos reales, no memoria:

1. [`docs/STATUS.md`](docs/STATUS.md) marca Fases 1–8 hechas. [`AGENTS.md`](AGENTS.md) §10.1 siguiente número libre = **9 Worker**. No saltar a retries/DLQ (10): no hay nada que reintentar si nadie despacha. No saltar a README polish (11) ni Compose (12).
2. [`app/services/queue.py`](app/services/queue.py) es un Protocol + lista en RAM. El docstring ya dice que Celery entra en una fase posterior. [`app/main.py`](app/main.py) asigna `InMemoryNotificationQueue()` siempre. [`NotificationService.accept`](app/services/notification_service.py) hace `commit` y luego `enqueue(id)` — el puerto ya está listo para cambiar de adapter.
3. [`app/workers/`](app/workers/__init__.py) y [`app/providers/`](app/providers/__init__.py) son stubs de Fase 1. Cero tasks. Cero `NotificationProvider`.
4. [`app/domain/state_machine.py`](app/domain/state_machine.py) ya prohíbe `PENDING → SENT`. El worker **debe** persistir `PROCESSING`. [`InvalidStatusTransition`](app/domain/exceptions.py) aún no tiene mapper HTTP; el worker no es HTTP.
5. [`NotificationRepository`](app/repositories/notification_repository.py) no tiene `get_by_id` sin `client_id`. El worker no es un cliente con API key.
6. [`pyproject.toml`](pyproject.toml) no lista `celery`. `import celery` falla en el venv.
7. Ejemplo de uso: `POST /send` → 202 `{status: PENDING}`. Sin worker, `GET /status` se queda `PENDING` para siempre (hoy). Con worker: el mismo `GET /status` pasa a `SENT` y `GET /metrics` muestra `sent: 1`. FastAPI **no** espera al email.

---

## 2. Árbol al cerrar esta fase

```text
pyproject.toml                                 # EDITAR: celery[redis] runtime
.env.example                                   # EDITAR: CELERY_BROKER_URL
app/core/config.py                             # EDITAR: celery_broker_url
app/services/queue.py                          # EDITAR: CeleryNotificationQueue; InMemory se queda
app/services/dispatch.py                       # NUEVO: DispatchService
app/services/__init__.py                       # EDITAR: export DispatchService + CeleryNotificationQueue
app/repositories/notification_repository.py    # EDITAR: get_by_id
app/providers/__init__.py                      # EDITAR: docstring + exports
app/providers/port.py                          # NUEVO: OutboundMessage, ProviderError, Protocol
app/providers/simulated.py                     # NUEVO: SimulatedNotificationProvider
app/workers/__init__.py                        # EDITAR: docstring
app/workers/celery_app.py                      # NUEVO: Celery app + conf
app/workers/runtime.py                         # NUEVO: engine/session del worker
app/workers/tasks.py                           # NUEVO: deliver_notification(id: str)
app/main.py                                    # EDITAR: lifespan elige InMemory vs Celery queue
app/api/routers/notifications.py               # EDITAR: docstring (el router sigue sin enviar)
tests/conftest.py                              # EDITAR: CELERY_BROKER_URL en el env de pytest
tests/unit/test_config.py                      # EDITAR: fail-fast CELERY_BROKER_URL
tests/unit/test_queue.py                       # no tocar (InMemory sigue)
tests/unit/test_celery_queue.py                # NUEVO: apply_async + QueueUnavailableError
tests/unit/providers/test_simulated.py         # NUEVO: simulado no hace I/O
tests/unit/services/test_dispatch_service.py   # NUEVO: SENT / skip / FAILED / missing
tests/integration/test_notification_repository.py  # EDITAR: get_by_id
tests/integration/test_dispatch.py             # NUEVO: Postgres real PENDING → SENT
README.md                                      # EDITAR: segundo proceso celery + curl status SENT
docs/STATUS.md                                 # EDITAR en el último paso de implementación
```

**No crear:** `Dockerfile`, `docker-compose.yml`, revisión Alembic, `app/workers/beat.py`, `notifications.dlq`, `BackgroundTasks`, `app/providers/twilio.py`, result backend.

**No tocar:** máquina de estados (tabla ya correcta), modelos/columnas, `GET /health`, Token Bucket / middleware 429, `NotificationService.accept` / `get_status`, `MetricsService`, `hash_api_key`, `create_all`, routers de metrics/clients más allá del docstring de notifications, `AuthenticatedClient`.

---

## 3. Git

Fase 8 **ya** está en `origin/main` (`03c28d6`, mismo árbol que `ea4da85`). Crear la rama así:

```bash
git checkout origin/main
# HEAD esperado: 03c28d6
git checkout -b feat/phase-9-celery-worker
```

Equivalente válido: `git checkout feat/phase-8-token-bucket && git checkout -b feat/phase-9-celery-worker` (árbol idéntico).

**Nunca** partir de `main` local (`7a2b828`). **Nunca** commitear en `main`.

Antes de cerrar cada paso de código:

```bash
source .venv/bin/activate
pytest -q
ruff check app tests
```

Los 90 tests de Fases 2–8 deben seguir verdes (más los nuevos de esta fase).

---

## FASE 0 — Preparación

- [ ] `pytest -q` → 90 passed **antes** de editar
- [ ] `ruff check app tests` limpio
- [ ] Rama `feat/phase-9-celery-worker` creada desde `origin/main` (`03c28d6`)
- [ ] Redis local ya corre (Fase 8): `redis-cli ping` → `PONG`. No hace falta un segundo servidor. El índice `/1` existe solo con `SELECT 1`.
- [ ] Cero Docker, cero Beat, cero Twilio, cero `BackgroundTasks`
- [ ] Enseñar a EsrgaN (ejemplo): **Celery** es un cocinero en la trastienda. FastAPI es el mostrador: toma el pedido, lo anota en un ticket (Postgres `PENDING`) y lo clava en un rail (Redis índice 1). El mostrador **no** cocina. El cocinero lee el ticket, pone “en preparación” (`PROCESSING`), cocina de mentira (provider simulado) y marca “listo” (`SENT`). Si el mostrador cocinara (`BackgroundTasks` o Twilio dentro del `POST`), un cliente lento o un uvicorn reiniciado quemaría el email a medias. **Worker** = ese proceso cocinero. **Broker** = el rail de tickets. **Provider** = la cocina (hoy de cartón; mañana Twilio detrás del mismo enchufe).

---

## FASE 9 — Celery + provider simulado

### Paso 9.1 — Settings + dependencia `celery`

Editar [`pyproject.toml`](pyproject.toml). Añadir a `dependencies` (junto a `redis`, **no** en dev):

```toml
    "celery[redis]>=5.4,<6",
```

Instalar en el venv:

```bash
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Editar [`.env.example`](.env.example) — el archivo completo queda:

```dotenv
APP_NAME=notifications-engine
ENVIRONMENT=local
LOG_LEVEL=INFO
SECRET_KEY=dev-secret-change-me
DATABASE_URL=postgresql+psycopg://USER@localhost:5432/notifications_engine
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
RATE_LIMIT_PER_MINUTE=10
```

Quien ya tenga `.env` debe copiar `CELERY_BROKER_URL` a mano (no commitear `.env`).

Editar [`app/core/config.py`](app/core/config.py). El archivo queda así (completo):

```python
"""Application settings loaded from the environment.

`secret_key`, `database_url`, `redis_url`, and `celery_broker_url` are required
so a misconfigured process fails at boot instead of running with silent empty config.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PSYCOPG_URL_PREFIX = "postgresql+psycopg://"
_REDIS_URL_PREFIX = "redis://"


class Settings(BaseSettings):
    """Fail-fast settings: boot dies without secrets and reachable-store URLs."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "notifications-engine"
    environment: Literal["local", "test", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    secret_key: SecretStr = Field(min_length=16)
    database_url: SecretStr = Field(min_length=1)
    redis_url: SecretStr = Field(min_length=1)
    celery_broker_url: SecretStr = Field(min_length=1)
    rate_limit_per_minute: int = Field(default=10, ge=1)

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        """Accept lowercase env values and normalize to the Literal uppercase set."""
        if isinstance(value, str):
            return value.upper()
        return value

    @field_validator("database_url")
    @classmethod
    def require_psycopg_url(cls, value: SecretStr) -> SecretStr:
        """Reject SQLite and bare postgresql:// so the driver matches the locked stack."""
        raw = value.get_secret_value()
        if not raw.startswith(_PSYCOPG_URL_PREFIX):
            raise ValueError(
                "DATABASE_URL must start with 'postgresql+psycopg://' "
                "(psycopg v3 driver required)"
            )
        return value

    @field_validator("redis_url")
    @classmethod
    def require_redis_url(cls, value: SecretStr) -> SecretStr:
        """Reject anything that is not a redis:// URL (no Unix socket, no rediss yet)."""
        raw = value.get_secret_value()
        if not raw.startswith(_REDIS_URL_PREFIX):
            raise ValueError("REDIS_URL must start with 'redis://'")
        return value

    @field_validator("celery_broker_url")
    @classmethod
    def require_celery_broker_url(cls, value: SecretStr) -> SecretStr:
        """Broker must be redis:// on a dedicated index, not a hidden default."""
        raw = value.get_secret_value()
        if not raw.startswith(_REDIS_URL_PREFIX):
            raise ValueError("CELERY_BROKER_URL must start with 'redis://'")
        return value


@lru_cache
def get_settings() -> Settings:
    """Cached settings so every request does not re-read the environment."""
    return Settings()
```

Editar [`tests/conftest.py`](tests/conftest.py): después de `REDIS_URL`, **antes** de importar `app.main`:

```python
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
```

Editar [`tests/unit/test_config.py`](tests/unit/test_config.py): extrae `_TEST_CELERY_BROKER_URL = "redis://localhost:6379/1"` y **añádelo** a cada test existente que construye `Settings(_env_file=None)` (si no, el fail-fast nuevo los rompe). Añade:

```python
_TEST_CELERY_BROKER_URL = "redis://localhost:6379/1"


def test_missing_celery_broker_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_celery_broker_url_without_redis_prefix_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
    monkeypatch.setenv("CELERY_BROKER_URL", "amqp://localhost")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

`test_valid_secret_key_is_not_in_repr` debe setear `CELERY_BROKER_URL`. `celery_broker_url` es `SecretStr`.

[`tests/unit/test_logging.py`](tests/unit/test_logging.py) usa `Settings(_env_file=None)` y se apoya en el env de `conftest`; con el `setdefault` basta. No lo reescribas salvo que pytest lo rompa.

- **Patrón:** fail-fast configuration (`pydantic-settings`).
- **Por qué ahora:** esta fase **abre** el broker. El playbook prohibía exigir URLs *antes* de abrirlas; ya no aplica.
- **Alternativa descartada:** derivar `/1` desde `REDIS_URL` con un replace. Un typo dejaría cubo y broker en el mismo índice y nadie lo vería en el `.env`. URL explícita enseña “dos usos, dos sitios”.
- **Capa:** `app/core/`. No importa FastAPI ni Celery.

- **Commit (si EsrgaN autoriza):**

```text
chore: require CELERY_BROKER_URL and pin Celery

Fail boot without a dedicated Redis index so the worker broker
cannot silently share the token-bucket database.
```

---

### Paso 9.2 — Puerto de provider + simulado

Crear [`app/providers/port.py`](app/providers/port.py). Responsabilidad: el enchufe. Quién lo implementa: adapters. Quién lo llama: `DispatchService`. **No** HTTP, **no** Celery.

```python
"""Application-owned provider port.

Workers call this; routers must not. Retry policy lives in the worker (later),
not inside an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.enums import Channel


class ProviderError(Exception):
    """The channel adapter could not deliver. Dispatch maps this to FAILED."""


@dataclass(frozen=True)
class OutboundMessage:
    """What the provider needs to deliver. No ORM, no HTTP, no API key."""

    channel: Channel
    recipient: str
    template: str
    payload: dict[str, Any]


class NotificationProvider(Protocol):
    """Port: send one already-accepted notification payload."""

    def send(self, message: OutboundMessage) -> None:
        """Deliver ``message``. Raise ``ProviderError`` on failure. Return None on success."""
        ...
```

Crear [`app/providers/simulated.py`](app/providers/simulated.py):

```python
"""In-process adapter. Logs a send; never talks to a vendor."""

from __future__ import annotations

import logging

from app.providers.port import OutboundMessage

logger = logging.getLogger("app.providers.simulated")


class SimulatedNotificationProvider:
    """v1 channel adapter: always succeeds, no network."""

    def send(self, message: OutboundMessage) -> None:
        logger.info(
            "simulated_send",
            extra={
                "channel": message.channel.value,
                "template": message.template,
            },
        )
```

No loguees `recipient` completo (PII). No `time.sleep`. No `random` para fallar “a veces” (eso es Fase 10 y ensuciaría el demo local).

Editar [`app/providers/__init__.py`](app/providers/__init__.py):

```python
"""Channel provider adapters. v1 ships a simulated adapter behind the port."""

from app.providers.port import NotificationProvider, OutboundMessage, ProviderError
from app.providers.simulated import SimulatedNotificationProvider

__all__ = [
    "NotificationProvider",
    "OutboundMessage",
    "ProviderError",
    "SimulatedNotificationProvider",
]
```

Crear [`tests/unit/providers/test_simulated.py`](tests/unit/providers/test_simulated.py):

```python
from app.domain.enums import Channel
from app.providers.port import OutboundMessage
from app.providers.simulated import SimulatedNotificationProvider


def test_simulated_send_returns_without_raising() -> None:
    provider = SimulatedNotificationProvider()
    provider.send(
        OutboundMessage(
            channel=Channel.EMAIL,
            recipient="user@example.com",
            template="welcome",
            payload={"name": "Ada"},
        )
    )


def test_simulated_send_accepts_every_channel() -> None:
    provider = SimulatedNotificationProvider()
    for channel in Channel:
        provider.send(
            OutboundMessage(
                channel=channel,
                recipient="dest",
                template="t",
                payload={},
            )
        )
```

Cero sockets. Cero Twilio. Cero FastAPI.

- **Patrón:** puerto / adapter (hexagonal). El dominio no conoce Twilio; el worker tampoco importa un SDK.
- **Por qué simulado ahora:** ejemplo: sin este enchufe, el worker haría `import twilio` y mañana cambiar de vendor reescribe la task. Con el puerto, Fase 10–12 enchufan Mailtrap detrás de la misma firma.
- **Alternativa descartada:** llamar a un SMTP local en esta fase. Enseña red, no el puerto; y los tests dejarían de ser unitarios.
- **Capa:** `app/providers/`. Puede usar dominio (`Channel`). No puede importar `app.api` ni `app.workers`.

- **Commit (si EsrgaN autoriza):**

```text
feat: add a simulated notification provider port

Keep vendor I/O behind a protocol so the worker never imports
a channel SDK.
```

---

### Paso 9.3 — `get_by_id` + `DispatchService`

Editar [`app/repositories/notification_repository.py`](app/repositories/notification_repository.py). Añadir **después** de `get_by_id_for_client`:

```python
    def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        """Load by primary key. Worker path only; not an HTTP authorization check."""
        return self._session.get(Notification, notification_id)
```

Editar [`tests/integration/test_notification_repository.py`](tests/integration/test_notification_repository.py). Añadir:

```python
def test_get_by_id_returns_row_without_client_filter(db_session: Session) -> None:
    owner = _client(db_session)
    repo = NotificationRepository(db_session)
    row = repo.create(
        client_id=owner.id,
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={},
        idempotency_key=None,
    )
    db_session.flush()
    loaded = repo.get_by_id(row.id)
    assert loaded is not None
    assert loaded.id == row.id
    assert repo.get_by_id(uuid.uuid4()) is None
```

Crear [`app/services/dispatch.py`](app/services/dispatch.py). Responsabilidad: transicionar y llamar al puerto. Quién lo llama: la task Celery. **No** FastAPI.

```python
"""Use case: dispatch one persisted notification through a provider port."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.domain.enums import NotificationStatus
from app.domain.state_machine import assert_transition
from app.providers.port import OutboundMessage, ProviderError
from app.repositories.notification_repository import NotificationRepository

logger = logging.getLogger("app.dispatch")

_ERROR_MESSAGE_MAX = 512


class DispatchService:
    def __init__(
        self,
        session: Session,
        repository: NotificationRepository,
        provider: object,
    ) -> None:
        self._session = session
        self._repository = repository
        self._provider = provider

    def dispatch(self, notification_id: uuid.UUID) -> None:
        """Load, skip terminals, PROCESSING → provider → SENT or FAILED. Commits here."""
        row = self._repository.get_by_id(notification_id)
        if row is None:
            logger.warning(
                "notification_dispatch_missing",
                extra={"notification_id": str(notification_id)},
            )
            return

        if row.status in {NotificationStatus.SENT, NotificationStatus.FAILED}:
            logger.info(
                "notification_dispatch_skipped",
                extra={
                    "notification_id": str(row.id),
                    "client_id": str(row.client_id),
                    "channel": row.channel.value,
                    "status": row.status.value,
                    "retry_count": row.retry_count,
                },
            )
            return

        if row.status is NotificationStatus.PENDING:
            assert_transition(row.status, NotificationStatus.PROCESSING)
            row.status = NotificationStatus.PROCESSING
            self._session.commit()

        logger.info(
            "notification_dispatch_started",
            extra={
                "notification_id": str(row.id),
                "client_id": str(row.client_id),
                "channel": row.channel.value,
                "status": row.status.value,
                "retry_count": row.retry_count,
            },
        )

        message = OutboundMessage(
            channel=row.channel,
            recipient=row.recipient,
            template=row.template,
            payload=row.payload,
        )
        try:
            self._provider.send(message)
        except Exception as exc:
            error = exc if isinstance(exc, ProviderError) else ProviderError(str(exc))
            assert_transition(row.status, NotificationStatus.FAILED)
            row.status = NotificationStatus.FAILED
            row.error_message = str(error)[:_ERROR_MESSAGE_MAX]
            self._session.commit()
            logger.info(
                "notification_dispatch_failed",
                extra={
                    "notification_id": str(row.id),
                    "client_id": str(row.client_id),
                    "channel": row.channel.value,
                    "status": row.status.value,
                    "retry_count": row.retry_count,
                },
                exc_info=True,
            )
            return

        assert_transition(row.status, NotificationStatus.SENT)
        row.status = NotificationStatus.SENT
        row.sent_at = datetime.now(UTC)
        row.error_message = None
        self._session.commit()
        logger.info(
            "notification_sent",
            extra={
                "notification_id": str(row.id),
                "client_id": str(row.client_id),
                "channel": row.channel.value,
                "status": row.status.value,
                "retry_count": row.retry_count,
            },
        )
```

El type de `provider` es `object` a propósito en el hint público si MyPy se queja del Protocol estructural; preferí anotar `NotificationProvider` si MyPy lo acepta sin ignore:

```python
        provider: NotificationProvider,
```

Usa `NotificationProvider` (el Protocol). No uses `Any` en la firma pública.

Editar [`app/services/__init__.py`](app/services/__init__.py) para exportar `DispatchService` y `CeleryNotificationQueue` (esta última en el paso 9.4; puedes exportarla entonces).

Crear [`tests/unit/services/test_dispatch_service.py`](tests/unit/services/test_dispatch_service.py):

```python
from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.domain.enums import Channel, NotificationStatus
from app.models.notification import Notification
from app.providers.port import OutboundMessage, ProviderError
from app.services.dispatch import DispatchService


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1


class FakeNotificationRepository:
    def __init__(self, row: Notification | None) -> None:
        self.row = row

    def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        if self.row is None or self.row.id != notification_id:
            return None
        return self.row


class RecordingProvider:
    def __init__(self) -> None:
        self.messages: list[OutboundMessage] = []

    def send(self, message: OutboundMessage) -> None:
        self.messages.append(message)


class BoomProvider:
    def send(self, message: OutboundMessage) -> None:
        raise ProviderError("vendor 500")


def _row(
    *,
    status: NotificationStatus = NotificationStatus.PENDING,
    notification_id: uuid.UUID | None = None,
) -> Notification:
    return Notification(
        id=notification_id or uuid.uuid4(),
        client_id=uuid.uuid4(),
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={"n": 1},
        status=status,
        retry_count=0,
    )


def test_pending_becomes_sent_and_calls_provider_once() -> None:
    row = _row()
    session = FakeSession()
    provider = RecordingProvider()
    service = DispatchService(session, FakeNotificationRepository(row), provider)

    service.dispatch(row.id)

    assert row.status is NotificationStatus.SENT
    assert row.sent_at is not None
    assert session.commit_calls == 2
    assert len(provider.messages) == 1
    assert provider.messages[0].template == "welcome"


def test_already_sent_does_not_call_provider() -> None:
    row = _row(status=NotificationStatus.SENT)
    provider = RecordingProvider()
    session = FakeSession()
    service = DispatchService(session, FakeNotificationRepository(row), provider)

    service.dispatch(row.id)

    assert provider.messages == []
    assert session.commit_calls == 0
    assert row.status is NotificationStatus.SENT


def test_already_failed_does_not_call_provider() -> None:
    row = _row(status=NotificationStatus.FAILED)
    provider = RecordingProvider()
    service = DispatchService(session, FakeNotificationRepository(row), provider)

    service.dispatch(row.id)

    assert provider.messages == []
    assert session.commit_calls == 0


def test_processing_crash_recovery_sends_without_second_pending_transition() -> None:
    row = _row(status=NotificationStatus.PROCESSING)
    provider = RecordingProvider()
    session = FakeSession()
    service = DispatchService(session, FakeNotificationRepository(row), provider)

    service.dispatch(row.id)

    assert row.status is NotificationStatus.SENT
    assert session.commit_calls == 1
    assert len(provider.messages) == 1


def test_provider_error_marks_failed() -> None:
    row = _row()
    session = FakeSession()
    service = DispatchService(session, FakeNotificationRepository(row), BoomProvider())

    service.dispatch(row.id)

    assert row.status is NotificationStatus.FAILED
    assert row.error_message == "vendor 500"
    assert row.sent_at is None
    assert session.commit_calls == 2


def test_missing_row_is_a_noop() -> None:
    session = FakeSession()
    provider = RecordingProvider()
    service = DispatchService(session, FakeNotificationRepository(None), provider)

    service.dispatch(uuid.uuid4())

    assert provider.messages == []
    assert session.commit_calls == 0
```

Quita el `import pytest` si no lo usas. Cero `time.sleep`. Cero dominio mockeado: usas la máquina de estados de verdad.

Crear [`tests/integration/test_dispatch.py`](tests/integration/test_dispatch.py) — Postgres real, provider fake (no Celery vivo):

```python
import uuid

from sqlalchemy import Engine

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.domain.enums import Channel, NotificationStatus
from app.models import Client, Notification
from app.providers.port import OutboundMessage
from app.repositories.notification_repository import NotificationRepository
from app.services.dispatch import DispatchService


class RecordingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, message: OutboundMessage) -> None:
        self.calls += 1


def test_dispatch_persists_sent_and_sent_at(persistence_engine: Engine) -> None:
    factory = create_session_factory(persistence_engine)
    provider = RecordingProvider()
    notification_id = uuid.uuid4()
    client_id: uuid.UUID
    with factory() as session:
        client = Client(
            name="dispatch-it",
            hashed_api_key=hash_api_key(generate_api_key()),
            is_active=True,
        )
        session.add(client)
        session.flush()
        client_id = client.id
        session.add(
            Notification(
                id=notification_id,
                client_id=client_id,
                channel=Channel.EMAIL,
                recipient="user@example.com",
                template="welcome",
                payload={},
                status=NotificationStatus.PENDING,
            )
        )
        session.commit()
    try:
        with factory() as session:
            service = DispatchService(
                session, NotificationRepository(session), provider
            )
            service.dispatch(notification_id)
        with factory() as session:
            row = session.get(Notification, notification_id)
            assert row is not None
            assert row.status is NotificationStatus.SENT
            assert row.sent_at is not None
        assert provider.calls == 1
    finally:
        with factory() as session:
            session.delete(session.get(Notification, notification_id))
            session.delete(session.get(Client, client_id))
            session.commit()
```

- **Patrón:** application service (use case) + repository + state machine. El worker no tiene lógica de negocio pegada al decorador `@task`.
- **Por qué dos commits:** ejemplo: `GET /status` mientras el simulado “envía” puede mostrar `PROCESSING`. Si saltaras a `SENT` en un solo write, violarías `PENDING → SENT`.
- **Alternativa descartada:** transicionar dentro de `tasks.py`. La task dejaría de ser serializable-y-tonta; testearla exigiría Celery. El servicio se testea con fakes.
- **Capa:** `app/services/` + `app/repositories/`. No importa FastAPI ni el módulo de tasks.

- **Commit (si EsrgaN autoriza):**

```text
feat: dispatch PENDING notifications through the provider port

Persist PROCESSING then SENT in the application service so the
worker task stays a thin id-only entrypoint.
```

---

### Paso 9.4 — Celery app + task + adapter de cola

Crear [`app/workers/celery_app.py`](app/workers/celery_app.py). Responsabilidad: configurar Celery. Quién lo arranca: CLI `celery -A …`. **No** importa routers.

```python
"""Celery application. Broker is Redis index 1; results are ignored (Postgres wins)."""

from celery import Celery
from kombu import Queue

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery("notifications_engine", include=["app.workers.tasks"])
celery_app.conf.update(
    broker_url=_settings.celery_broker_url.get_secret_value(),
    result_backend=None,
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="notifications",
    task_queues=(Queue("notifications"),),
    timezone="UTC",
    enable_utc=True,
    task_acks_on_failure_or_timeout=True,
)
```

Si MyPy se queja de `celery` / `kombu`, añade en este archivo (no un paquete extra):

```python
from celery import Celery  # type: ignore[import-untyped]
from kombu import Queue  # type: ignore[import-untyped]
```

Solo esos dos ignores, no `mypy ignore_missing_imports` global.

Crear [`app/workers/runtime.py`](app/workers/runtime.py):

```python
"""Worker composition root: one engine per process, one session per task."""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.db import create_engine_from_url, create_session_factory
from app.core.logging import configure_logging

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_worker_session_factory() -> sessionmaker[Session]:
    """Lazily build the worker engine. FastAPI lifespan must not call this."""
    global _engine, _session_factory
    if _session_factory is None:
        settings = get_settings()
        configure_logging(settings)
        _engine = create_engine_from_url(settings.database_url.get_secret_value())
        _session_factory = create_session_factory(_engine)
    return _session_factory
```

Crear [`app/workers/tasks.py`](app/workers/tasks.py):

```python
"""Celery tasks. Payloads are ids; work lives in DispatchService."""

from __future__ import annotations

import uuid

from app.providers.simulated import SimulatedNotificationProvider
from app.repositories.notification_repository import NotificationRepository
from app.services.dispatch import DispatchService
from app.workers.celery_app import celery_app
from app.workers.runtime import get_worker_session_factory


@celery_app.task(name="notifications.deliver", ignore_result=True, max_retries=0)
def deliver_notification(notification_id: str) -> None:
    """Load the row and dispatch. Never import FastAPI routers."""
    factory = get_worker_session_factory()
    session = factory()
    try:
        service = DispatchService(
            session=session,
            repository=NotificationRepository(session),
            provider=SimulatedNotificationProvider(),
        )
        service.dispatch(uuid.UUID(notification_id))
    finally:
        session.close()
```

Editar [`app/workers/__init__.py`](app/workers/__init__.py):

```python
"""Celery workers. Tasks receive notification ids, never ORM objects or HTTP."""
```

Editar [`app/services/queue.py`](app/services/queue.py). El Protocol y `InMemoryNotificationQueue` **se quedan**. Añade el adapter Celery al final. El archivo completo queda:

```python
"""Queue port for accepted notifications.

The HTTP path enqueues an id; it never talks to a provider.
InMemoryNotificationQueue is the test adapter. CeleryNotificationQueue is local/prod.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, Protocol


class QueueUnavailableError(Exception):
    """Raised when enqueue cannot complete. HTTP handler maps this to 503."""


class NotificationQueue(Protocol):
    """Application-owned port: accept a notification id for later dispatch."""

    def enqueue(self, notification_id: uuid.UUID) -> None:
        """Record ``notification_id``. Must not send the notification.

        Adapters may raise ``QueueUnavailableError``.
        """
        ...


class InMemoryNotificationQueue:
    """Process-local list. Lost on restart; Postgres still holds PENDING rows."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    def enqueue(self, notification_id: uuid.UUID) -> None:
        self.enqueued.append(notification_id)


class CeleryNotificationQueue:
    """Publish notification ids to the Celery ``notifications`` queue."""

    def __init__(self, apply_async: Callable[..., Any] | None = None) -> None:
        self._apply_async = apply_async

    def enqueue(self, notification_id: uuid.UUID) -> None:
        publish = self._apply_async
        if publish is None:
            from app.workers.tasks import deliver_notification

            publish = deliver_notification.apply_async
        try:
            publish(args=[str(notification_id)], queue="notifications")
        except QueueUnavailableError:
            raise
        except Exception as exc:
            raise QueueUnavailableError() from exc
```

Editar [`app/services/__init__.py`](app/services/__init__.py):

```python
"""Application services: use cases orchestrating domain and ports."""

from app.services.dispatch import DispatchService
from app.services.metrics_service import MetricsService
from app.services.notification_service import NotificationService
from app.services.queue import (
    CeleryNotificationQueue,
    InMemoryNotificationQueue,
    NotificationQueue,
    QueueUnavailableError,
)

__all__ = [
    "CeleryNotificationQueue",
    "DispatchService",
    "InMemoryNotificationQueue",
    "MetricsService",
    "NotificationQueue",
    "NotificationService",
    "QueueUnavailableError",
]
```

Editar [`app/main.py`](app/main.py). Import de cola: deja `InMemoryNotificationQueue` y `QueueUnavailableError`. **No** importes `CeleryNotificationQueue` arriba (evita arrancar Celery en cada test). Dentro de `lifespan`, **reemplaza** la línea que asigna `notification_queue`:

```python
    if settings.environment == "test":
        application.state.notification_queue = InMemoryNotificationQueue()
    else:
        from app.services.queue import CeleryNotificationQueue

        application.state.notification_queue = CeleryNotificationQueue()
```

El Redis del Token Bucket **no cambia** (sigue FakeRedis en test, índice 0 en local).

Editar el docstring de [`app/api/routers/notifications.py`](app/api/routers/notifications.py) (primera línea):

```python
"""Accept-send and status probe. The worker process dispatches; this router does not."""
```

El body de los endpoints **no se toca**.

Crear [`tests/unit/test_celery_queue.py`](tests/unit/test_celery_queue.py):

```python
from __future__ import annotations

import uuid

import pytest

from app.services.queue import CeleryNotificationQueue, QueueUnavailableError


def test_enqueue_publishes_str_id_on_notifications_queue() -> None:
    seen: dict[str, object] = {}

    def fake_apply_async(*, args: list[str], queue: str) -> None:
        seen["args"] = args
        seen["queue"] = queue

    notification_id = uuid.uuid4()
    CeleryNotificationQueue(apply_async=fake_apply_async).enqueue(notification_id)

    assert seen["args"] == [str(notification_id)]
    assert seen["queue"] == "notifications"


def test_enqueue_wraps_broker_errors() -> None:
    def boom(*, args: list[str], queue: str) -> None:
        raise ConnectionError("broker down")

    with pytest.raises(QueueUnavailableError):
        CeleryNotificationQueue(apply_async=boom).enqueue(uuid.uuid4())
```

[`tests/integration/test_send.py`](tests/integration/test_send.py) **sigue** afirmando `isinstance(queue, InMemoryNotificationQueue)` y status `PENDING`. Si eso se pone rojo, el lifespan de test está mal (D12).

Cero worker vivo en pytest. Cero `task_always_eager` global.

- **Patrón:** adapter del puerto de cola + task id-only + composition root del worker.
- **Por qué JSON y no pickle:** ejemplo: un pickle ejecuta clases al deserializar. JSON solo mueve el string del UUID. A esta escala no necesitamos speed de pickle.
- **Por qué `acks_late`:** ejemplo: el worker muere después de marcar `PROCESSING` y antes de acabar. Si ack-eara al empezar, el ticket se perdería. Con ack al final, Redis lo reentrega; `SENT`/`FAILED` evitan un segundo email si ya terminó.
- **Alternativa descartada:** `BackgroundTasks` de FastAPI. Muere con el proceso; no hay rail. El charter lo prohíbe.
- **Capa:** `app/workers/` (Celery) + `app/services/queue.py` (adapter). Routers no importan Celery.

- **Commit (si EsrgaN autoriza):**

```text
feat: enqueue accepted notifications onto Celery

Keep FastAPI on the 202 path and let a second venv process
dispatch ids through Redis index 1.
```

---

### Paso 9.5 — Docs de status + README

Editar [`docs/STATUS.md`](docs/STATUS.md) **solo al cerrar la implementación** (otro turno). Este turno de PLAN **no** marca Fase 9 hecha. Cuando el código exista:

- Marcar Fase 9 hecha: Celery en el venv, broker `/1`, provider simulado, `DispatchService`, `PENDING → PROCESSING → SENT`, tests sin worker vivo.
- Decir qué **sigue**: Fase 10 = retries 5s/15s/45s + `FAILED` + cola `notifications.dlq`.
- “Qué no existe” **deja de listar** Celery / provider simulado. Sigue incluyendo DLQ, Beat, Docker, mapper de `InvalidStatusTransition`, Mailtrap/Twilio reales.
- No marcar Fase 10 como hecha.

Editar [`README.md`](README.md) **en la implementación**:

- Status: “Phase 9: Celery worker in the same venv + simulated provider; FastAPI still returns 202 PENDING; poll GET /status until SENT”.
- `.env`: `CELERY_BROKER_URL=redis://localhost:6379/1` (distinto de `REDIS_URL` `/0`).
- Run: **dos** procesos:

```bash
# terminal 1
uvicorn app.main:app --reload --port 8000

# terminal 2 (same venv, repo root, .env present)
celery -A app.workers.celery_app worker --loglevel=INFO --queues=notifications
```

- Después del curl de send, documentar poll de status y metrics:

```bash
curl -i -H "X-API-Key: PASTE_RAW_KEY" \
  http://127.0.0.1:8000/api/v1/notifications/NOTIFICATION_ID/status
# 200 {"notification_id":"...","status":"SENT"}   # after the worker runs

curl -i -H "X-API-Key: PASTE_RAW_KEY" http://127.0.0.1:8000/api/v1/metrics
# 200 {"sent":1,"failed":0}
```

- Dejar claro: sin el proceso worker, `GET /status` se queda `PENDING` (eso es correcto). pytest **no** arranca Celery. Docker sigue “fase posterior”. Retries/DLQ no están.

- **Commit (si EsrgaN autoriza):**

```text
docs: record the local Celery worker and SENT poll
```

---

## 4. Checklist de cierre

- [ ] `pytest -q` verde (90 anteriores + config broker + simulado + dispatch unit + dispatch Postgres + celery queue)
- [ ] `ruff check app tests` limpio
- [ ] `app/domain/` sigue sin importar FastAPI/SQLAlchemy/Redis/Celery/Pydantic
- [ ] Routers **no** importan `app.workers` ni providers; `NotificationService.accept` intacto
- [ ] Worker **no** importa `app.api.routers`
- [ ] Cero `create_all`, cero migración nueva, cero `commit` en `get_db`
- [ ] HTTP test env: `POST /send` sigue 202 `PENDING` e `InMemoryNotificationQueue`
- [ ] `DispatchService`: PENDING→SENT (2 commits), skip SENT/FAILED, PROCESSING recovery, missing noop, ProviderError→FAILED
- [ ] Integración Postgres: fila acaba `SENT` con `sent_at` no nulo
- [ ] `CeleryNotificationQueue` publica `str(id)` en queue `notifications`; error de broker → `QueueUnavailableError`
- [ ] `GET /health` sigue 200 sin API key y sin I/O a Redis/Celery
- [ ] Token Bucket intacto (índice 0); broker es índice 1
- [ ] Cero `time.sleep`, cero worker vivo en pytest, cero `task_always_eager` global, cero Twilio, cero JWT, cero Docker, cero DLQ, cero Beat
- [ ] README: uvicorn + celery en el mismo venv; curl de status `SENT`
- [ ] 3–6 learning points en español **simple** para EsrgaN (mostrador vs cocina, por qué id y no ORM, por qué `/1` ≠ `/0`, por qué simulado, por qué InMemory en tests, por qué `PENDING → PROCESSING → SENT` y no un salto)
- [ ] Commits hechos o mensajes esperando a EsrgaN

**Prohibido al terminar:** retries/DLQ, `import twilio`, Compose, mapper HTTP de transiciones, mezclar cubo y broker en `/0`, `BackgroundTasks`, eager por defecto.

---

## 5. Qué sigue (no implementar)

Siguiente `PLAN.md` (otra reescritura): **retries + DLQ** (5s / 15s / 45s, máximo 5 intentos, `FAILED` + cola `notifications.dlq`). El worker de esta fase ya despacha el camino feliz. No implementar retries, DLQ, Beat, Docker ni providers reales en este turno.
