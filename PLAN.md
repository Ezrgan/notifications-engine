# PLAN.md — Fase 10: retries con backoff + cola `notifications.dlq`

> **REGLA OBLIGATORIA PARA TODOS LOS AGENTES:**
> Antes de ejecutar cualquier paso, leer y acatar [`AGENTS.md`](./AGENTS.md), [`.cursor/rules/`](./.cursor/rules/) (sobre todo `celery.mdc`, `testing.mdc`, `fastapi.mdc` y `anti-overengineering.mdc`) y [`docs/HOW_TO_WRITE_THE_NEXT_PLAN.md`](./docs/HOW_TO_WRITE_THE_NEXT_PLAN.md).
> Este archivo es el **único plan ejecutable**. Describe **una sola fase**. Cuando cierre, EsrgaN **reescribe** `PLAN.md` entero (ver el playbook en `docs/`).
> No implementar Beat, replay admin, JWT, alta HTTP de clientes, Prometheus, Mailtrap/Twilio reales ni Docker.

> **Cómo está pensado este documento:**
> Un agente debe poder implementarlo **sin inventar**. Cada paso: archivos exactos, contrato, tests, commit propuesto, qué no tocar.
> Código completo. Cero placeholders. Cero `# ... rest of code ...`.
> Enseñar a EsrgaN en **español simple**, con ejemplos. Sin jerga sin definir.

> **Estado de partida (verificado):**
> Rama actual `feat/phase-9-celery-worker` = `a602b2b` (phase 9 **no** está en `origin/main`).
> `origin/main` = `03c28d6` (fases 1–8). `main` local = `7a2b828` — **atrás**; no partir de ahí ni de `origin/main`.
> `pytest -q` → **105 passed**. `ruff check app tests` limpio. `mypy app` limpio.
> Hay worker Celery en el mismo venv, provider simulado que **siempre acierta**, `DispatchService` que ante cualquier error marca `FAILED` y termina (`max_retries=0`). Cero backoff. Cero cola `notifications.dlq`.
> HTTP (`POST /send` 202 `PENDING`, Token Bucket, metrics) **no cambia de contrato**.

---

## 0. Decisiones congeladas (esta fase)

| # | Decisión | Valor congelado |
| --- | --- | --- |
| D1 | Idea de la fase | Si el provider **falla de forma temporal** (timeout, 5xx), el worker **no** tira la toalla: espera y vuelve a intentar. Si se acaba el presupuesto o el fallo es **permanente** (destinatario mal, 4xx), la fila queda `FAILED` y el id se publica en la cola **`notifications.dlq`** para inspeccionar. Ejemplo: Mailtrap está caído 20 s → el email sale en el segundo intento. Un `recipient` inventado → `FAILED` al momento, sin esperar 5+15+45 s. |
| D2 | Presupuesto de intentos | **5 intentos** = 1 inicial + 4 reintentos. Setting `max_delivery_attempts` default **5**, `ge=1`. Ejemplo: `retry_count` empieza en 0; cada send fallido suma 1; cuando `retry_count` llega a 5, se acaba. |
| D3 | Backoff | Countdowns **5 s, 15 s, 45 s**. Intentos extra (el 4.º reintento, intento 5) **repiten 45 s** (tope). No continuar el factor 3 hasta 135 s: en local eso parece “colgado”. Env `DELIVERY_RETRY_COUNTDOWNS=5,15,45`. Función de dominio: índice `min(retry_count - 1, len(schedule) - 1)`. |
| D4 | Quién posee la regla | **`DeliveryRetryPolicy`** (dominio) decide *si* reintentar y *cuántos segundos*. **`DispatchService`** aplica transiciones, incrementa `retry_count`, persiste. **La task Celery** solo obedece el resultado (`self.retry` o publicar DLQ). El adapter **no** reintenta. |
| D5 | Transiente vs permanente | `TransientProviderError` y cualquier `Exception` no clasificada (incl. `ProviderError` pelado) → **reintentable**. `PermanentProviderError` → `FAILED` + DLQ **sin** backoff, aunque queden intentos. Ejemplo: “el horno está ocupado” vs “la dirección no existe”. |
| D6 | Máquina de estados | Reintento: `PROCESSING → PENDING` (ya es legal). Durante la espera, `GET /status` muestra `PENDING` otra vez (no `FAILED`). Agotado o permanente: `PROCESSING → FAILED`. `SENT` y `FAILED` siguen terminales: no se llama al provider. `PENDING → SENT` sigue ilegal. |
| D7 | `retry_count` | Entero en la fila (columna **ya existe**, cero Alembic). Se incrementa **después** de un send fallido, **antes** de decidir retry vs FAILED. Primer fallo transiente → `retry_count=1`, countdown 5 s. Quinto fallo → `retry_count=5` → FAILED. |
| D8 | Resultado del use case | `dispatch()` **devuelve** `DispatchResult` (`sent` / `skipped` / `missing` / `retry` / `failed`). `retry` lleva `countdown_seconds`. `failed` lleva `dead_letter=True`. Prohibido que `DispatchService` importe Celery. |
| D9 | Task Celery | `@task(bind=True, name="notifications.deliver")`. **Quitar** `max_retries=0`. Ante `RETRY`: `raise self.retry(countdown=..., max_retries=max_delivery_attempts - 1)`. Payload sigue siendo el UUID en string. |
| D10 | DLQ | Cola Kombu **`notifications.dlq`**. Task `notifications.dead_letter` (`record_dead_letter`): **solo log** `notification_dead_lettered` + el id. No llama al provider. No transiciona estado (la fila **ya** es `FAILED`). Publicar con `apply_async(args=[str(id)], queue="notifications.dlq")`. Broker Redis **no** tiene DLX de AMQP: la DLQ es una cola nombrada, no magia del broker. |
| D11 | Worker escucha las dos colas | Arranque: `--queues=notifications,notifications.dlq`. Así el demo local enseña la línea de log. Postgres `FAILED` es la **fuente de verdad**. Si el proceso muere entre el commit `FAILED` y el publish DLQ, el mensaje DLQ puede faltar; no añadas columna `dead_lettered_at`. |
| D12 | Simulado determinista | Template **exacto** `fail-transient` → `TransientProviderError`. Template **exacto** `fail-permanent` → `PermanentProviderError`. Cualquier otro template (p. ej. `welcome`) sigue acertando. Cero `random`. Cero `time.sleep`. Ejemplo curl: `"template":"fail-transient"` para ver reintentos. |
| D13 | HTTP intacto | Routers, 202, Token Bucket, auth, metrics, health: **no cambian**. `POST /send` no espera al backoff. `GET /metrics` sube `failed` **solo** cuando la fila es `FAILED`, no en cada reintento. Tests HTTP siguen con `InMemoryNotificationQueue`. |
| D14 | Tests | Cero `time.sleep`. Cero worker Celery vivo. Cero `task_always_eager` global. El backoff se **afirma** (countdown=5/15/45), no se espera. Fake provider en unit/integration. Cero Twilio. |
| D15 | Settings | `max_delivery_attempts: int = 5` (`ge=1`). `delivery_retry_countdowns: tuple[int, ...] = (5, 15, 45)` desde env CSV. Vacío o enteros `< 1` → `ValidationError` (fail-fast). Siguen obligatorios `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`. |
| D16 | Cero libs nuevas | Celery ya está. Prohibido Flower, celery-redbeat, `kombu` extra, Twilio, `httpx` de más, Kafka, JWT. |
| D17 | Logs | Eventos nuevos: `notification_retry_scheduled`, `notification_dead_lettered`. Los de Fase 9 se quedan. `extra=` con `notification_id`, `client_id`, `channel`, `status`, `retry_count`. Nunca API key ni payload completo ni recipient entero. |
| D18 | Fuera de esta fase | Celery Beat, UI de replay, mapper HTTP de `InvalidStatusTransition`, `ClientService`, cablear `Client.rate_limit_per_minute`, Mailtrap/Twilio, Dockerfile/Compose, result backend Redis, eager por defecto. |
| D19 | Git | Rama `feat/phase-10-retries-dlq` **desde** `feat/phase-9-celery-worker` (`a602b2b`). **No** desde `origin/main` (`03c28d6`, sin worker) ni `main` local (`7a2b828`). Commits **solo si EsrgaN lo pide**. |
| D20 | Docker / extras | Prohibidos. No Kafka, JWT, Prisma, Compose, segundo Redis, segundo broker. |

---

## 1. Diagnóstico (por qué esta fase)

Archivos reales, no memoria:

1. [`docs/STATUS.md`](docs/STATUS.md) marca Fases 1–9 hechas. [`AGENTS.md`](AGENTS.md) §10.1 siguiente número libre = **10 Retry + DLQ**. No saltar a README polish (11) ni Compose (12): el worker ya despacha el camino feliz, pero un Mailtrap caído **quema** el ticket a `FAILED` en el primer golpe ([`app/services/dispatch.py`](app/services/dispatch.py) líneas 77–96).
2. [`app/workers/tasks.py`](app/workers/tasks.py) tiene `max_retries=0`. [`app/workers/celery_app.py`](app/workers/celery_app.py) declara **solo** `Queue("notifications")`. Cero `notifications.dlq`.
3. [`app/providers/port.py`](app/providers/port.py) solo tiene `ProviderError`. [`app/providers/simulated.py`](app/providers/simulated.py) **nunca** lanza: no hay demo local de retry.
4. [`app/domain/state_machine.py`](app/domain/state_machine.py) **ya** permite `PROCESSING → PENDING`. [`Notification.retry_count`](app/models/notification.py) **ya** existe (default 0). Cero migración.
5. [`app/core/config.py`](app/core/config.py) no tiene presupuesto ni countdowns: hoy el `5` viviría como magia en la task, y `AGENTS.md` §5.6 lo prohíbe.
6. Ejemplo de uso: `POST /send` con `"template":"welcome"` → 202 → worker → `SENT` (igual que Fase 9). Con `"template":"fail-transient"` → el worker espera 5 s, 15 s, 45 s, 45 s; al 5.º fallo `GET /status` = `FAILED` y el log muestra `notification_dead_lettered`. FastAPI **no** espera esos segundos.

---

## 2. Árbol al cerrar esta fase

```text
.env.example                                      # EDITAR: MAX_DELIVERY_ATTEMPTS + DELIVERY_RETRY_COUNTDOWNS
app/core/config.py                                # EDITAR: esos dos campos + validator CSV
app/domain/retry_policy.py                        # NUEVO: DeliveryRetryPolicy
app/domain/__init__.py                            # EDITAR: export
app/providers/port.py                             # EDITAR: TransientProviderError, PermanentProviderError
app/providers/simulated.py                        # EDITAR: fail-transient / fail-permanent
app/providers/__init__.py                         # EDITAR: export subclasses
app/services/dispatch.py                          # EDITAR: policy + DispatchResult; ya no FAILED inmediato
app/workers/celery_app.py                         # EDITAR: Queue("notifications.dlq")
app/workers/tasks.py                              # EDITAR: bind=True, retry, record_dead_letter, apply_delivery_result
app/workers/__init__.py                           # EDITAR: docstring (retries + DLQ)
README.md                                         # EDITAR: backoff, templates de fallo, --queues con dlq
docs/STATUS.md                                    # EDITAR en el último paso de *implementación* (otro turno)
tests/unit/test_config.py                         # EDITAR: defaults + CSV inválido
tests/unit/domain/test_retry_policy.py            # NUEVO
tests/unit/providers/test_simulated.py            # EDITAR: templates de fallo
tests/unit/services/test_dispatch_service.py      # EDITAR: retry / permanente / agotado
tests/unit/workers/test_apply_delivery_result.py  # NUEVO
tests/integration/test_dispatch.py                # EDITAR: transiente→SENT; permanente→FAILED
```

**No crear:** `Dockerfile`, `docker-compose.yml`, revisión Alembic, `app/workers/beat.py`, `app/providers/twilio.py`, `BackgroundTasks`, result backend, columna `dead_lettered_at`.

**No tocar:** máquina de estados (la arista de retry **ya** está), modelos/columnas, `GET /health`, Token Bucket, `NotificationService.accept` / `get_status`, `MetricsService`, `hash_api_key`, routers (ni siquiera el docstring salvo si mientes), `CeleryNotificationQueue` (sigue publicando solo a `notifications`), `create_all`.

---

## 3. Git

Phase 9 vive **solo** en `feat/phase-9-celery-worker` (`a602b2b`). Crear la rama así:

```bash
git checkout feat/phase-9-celery-worker
# HEAD esperado: a602b2b
git checkout -b feat/phase-10-retries-dlq
```

**Nunca** partir de `origin/main` (`03c28d6`: no hay worker) ni de `main` local (`7a2b828`). **Nunca** commitear en `main`.

Antes de cerrar cada paso de código:

```bash
source .venv/bin/activate
pytest -q
ruff check app tests
mypy app
```

Los 105 tests de Fases 2–9 deben seguir verdes **después** de adaptar los de dispatch que hoy esperan `FAILED` inmediato ante `ProviderError` (paso 10.3). No dejes ese rojo “para después”.

---

## FASE 0 — Preparación

- [ ] `pytest -q` → 105 passed **antes** de editar
- [ ] `ruff check app tests` limpio; `mypy app` limpio
- [ ] Rama `feat/phase-10-retries-dlq` creada desde `feat/phase-9-celery-worker` (`a602b2b`)
- [ ] Redis local ya corre (Fases 8–9). No hace falta un segundo servidor.
- [ ] Cero Docker, cero Beat, cero Twilio, cero `BackgroundTasks`, cero Alembic
- [ ] Enseñar a EsrgaN (ejemplo): **Retry** = si el horno está ocupado, el ticket vuelve al rail y el cocinero lo retoma. **Backoff** = no golpear la puerta a cada segundo: espera 5 s, luego 15 s, luego 45 s. **Fallo permanente** = la dirección no existe; esperar no la inventa. **DLQ** (*Dead Letter Queue*) = cajón de tickets rotos para **mirarlos**, no una UI de reenvío. **Celery `self.retry`** = “vuelve a ponerme este mismo ticket en el rail dentro de N segundos”. El mostrador FastAPI **nunca** espera esos N segundos: el cliente ya tiene el `202` y el `notification_id`.

---

## FASE 10 — Retries + DLQ

### Paso 10.1 — Settings + política de dominio

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
MAX_DELIVERY_ATTEMPTS=5
DELIVERY_RETRY_COUNTDOWNS=5,15,45
```

Quien ya tenga `.env` debe copiar las dos líneas nuevas a mano (no commitear `.env`). Los **defaults** en `Settings` coinciden, así que un `.env` viejo sigue arrancando.

Editar [`app/core/config.py`](app/core/config.py). Añadir los campos **después** de `rate_limit_per_minute` y los validators **después** de `require_celery_broker_url`. El archivo completo queda:

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
    max_delivery_attempts: int = Field(default=5, ge=1)
    delivery_retry_countdowns: tuple[int, ...] = Field(default=(5, 15, 45))

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

    @field_validator("delivery_retry_countdowns", mode="before")
    @classmethod
    def parse_retry_countdowns(cls, value: object) -> object:
        """Accept CSV from env (5,15,45) or an already-parsed sequence."""
        if isinstance(value, str):
            parts = tuple(int(piece.strip()) for piece in value.split(",") if piece.strip())
            return parts
        return value

    @field_validator("delivery_retry_countdowns")
    @classmethod
    def require_positive_countdowns(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        """Empty or non-positive waits are not a backoff schedule."""
        if not value or any(seconds < 1 for seconds in value):
            raise ValueError(
                "DELIVERY_RETRY_COUNTDOWNS must be a comma-separated list of integers >= 1"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """Cached settings so every request does not re-read the environment."""
    return Settings()  # type: ignore[call-arg]
```

Crear [`app/domain/retry_policy.py`](app/domain/retry_policy.py). Responsabilidad: presupuesto y espera. Quién lo llama: `DispatchService`. **No** Celery, **no** FastAPI.

```python
"""Attempt budget and backoff. Numbers come from settings; this module is stdlib-only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryRetryPolicy:
    """How many sends are allowed and how long to wait after each transient failure."""

    max_attempts: int
    countdown_seconds: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if not self.countdown_seconds or any(seconds < 1 for seconds in self.countdown_seconds):
            raise ValueError("countdown_seconds must be a non-empty tuple of ints >= 1")

    def should_retry(self, retry_count: int, *, retryable: bool) -> bool:
        """``retry_count`` is attempts already burned, including the failure just counted."""
        return retryable and retry_count < self.max_attempts

    def countdown_for(self, retry_count: int) -> int:
        """Seconds to wait after this failed attempt. Extra attempts cap at the last slot."""
        if retry_count < 1:
            raise ValueError("retry_count must be >= 1 when asking for a countdown")
        index = min(retry_count - 1, len(self.countdown_seconds) - 1)
        return self.countdown_seconds[index]
```

Editar [`app/domain/__init__.py`](app/domain/__init__.py):

```python
"""Domain layer: channels, statuses, transitions, and named errors.

This package must not import FastAPI, Pydantic, SQLAlchemy, Redis, or Celery.
"""

from app.domain.enums import Channel, NotificationStatus
from app.domain.exceptions import DomainError, InvalidStatusTransition, NotificationNotFound
from app.domain.retry_policy import DeliveryRetryPolicy
from app.domain.state_machine import assert_transition, can_transition, transition

__all__ = [
    "Channel",
    "DeliveryRetryPolicy",
    "DomainError",
    "InvalidStatusTransition",
    "NotificationNotFound",
    "NotificationStatus",
    "assert_transition",
    "can_transition",
    "transition",
]
```

Crear [`tests/unit/domain/test_retry_policy.py`](tests/unit/domain/test_retry_policy.py):

```python
import pytest

from app.domain.retry_policy import DeliveryRetryPolicy

_POLICY = DeliveryRetryPolicy(max_attempts=5, countdown_seconds=(5, 15, 45))


def test_first_three_failures_use_schedule_then_cap() -> None:
    assert _POLICY.countdown_for(1) == 5
    assert _POLICY.countdown_for(2) == 15
    assert _POLICY.countdown_for(3) == 45
    assert _POLICY.countdown_for(4) == 45


def test_retry_while_budget_remains() -> None:
    assert _POLICY.should_retry(1, retryable=True) is True
    assert _POLICY.should_retry(4, retryable=True) is True
    assert _POLICY.should_retry(5, retryable=True) is False


def test_permanent_failure_never_retries() -> None:
    assert _POLICY.should_retry(1, retryable=False) is False


def test_single_attempt_budget_fails_fast() -> None:
    policy = DeliveryRetryPolicy(max_attempts=1, countdown_seconds=(5, 15, 45))
    assert policy.should_retry(1, retryable=True) is False


def test_invalid_policy_rejected() -> None:
    with pytest.raises(ValueError):
        DeliveryRetryPolicy(max_attempts=0, countdown_seconds=(5,))
    with pytest.raises(ValueError):
        DeliveryRetryPolicy(max_attempts=5, countdown_seconds=())
    with pytest.raises(ValueError):
        DeliveryRetryPolicy(max_attempts=5, countdown_seconds=(5, 0))
```

Editar [`tests/unit/test_config.py`](tests/unit/test_config.py). Añadir al final (los tests viejos siguen válidos: hay default):

```python
def test_delivery_retry_settings_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
    monkeypatch.setenv("CELERY_BROKER_URL", _TEST_CELERY_BROKER_URL)
    monkeypatch.delenv("MAX_DELIVERY_ATTEMPTS", raising=False)
    monkeypatch.delenv("DELIVERY_RETRY_COUNTDOWNS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.max_delivery_attempts == 5
    assert settings.delivery_retry_countdowns == (5, 15, 45)


def test_delivery_retry_countdowns_parse_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
    monkeypatch.setenv("CELERY_BROKER_URL", _TEST_CELERY_BROKER_URL)
    monkeypatch.setenv("DELIVERY_RETRY_COUNTDOWNS", "5,15,45")
    settings = Settings(_env_file=None)
    assert settings.delivery_retry_countdowns == (5, 15, 45)


def test_delivery_retry_countdowns_reject_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
    monkeypatch.setenv("CELERY_BROKER_URL", _TEST_CELERY_BROKER_URL)
    monkeypatch.setenv("DELIVERY_RETRY_COUNTDOWNS", "5,0,45")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_max_delivery_attempts_below_one_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
    monkeypatch.setenv("CELERY_BROKER_URL", _TEST_CELERY_BROKER_URL)
    monkeypatch.setenv("MAX_DELIVERY_ATTEMPTS", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

- **Patrón:** fail-fast configuration + regla de dominio pura (sin Celery).
- **Por qué ahora:** esta fase **abre** el presupuesto. Si el `5` y el `45` viven en `tasks.py`, no puedes enseñar “config vs magia” y un test no puede usar `max_attempts=2` sin parchear el módulo.
- **Alternativa descartada:** 5 s → 15 s → 45 s → **135 s** (seguir el ×3). En un demo local parece un hang; `AGENTS.md` §5.6 permite tope. El tope 45 s enseña “exponencial con techo”.
- **Capa:** `app/core/` (números) + `app/domain/` (regla). Domain no importa Settings.

- **Commit (si EsrgaN autoriza):**

```text
feat: configure delivery attempts and backoff in settings

Keep the 5-attempt budget and 5/15/45 schedule out of the
task module so tests can vary the policy without Celery.
```

---

### Paso 10.2 — Errores de provider + simulado determinista

Editar [`app/providers/port.py`](app/providers/port.py). El archivo completo queda:

```python
"""Application-owned provider port.

Workers call this; routers must not. Retry policy lives in DispatchService
and the worker task, not inside an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.enums import Channel


class ProviderError(Exception):
    """The channel adapter could not deliver. Unclassified errors are retryable."""


class TransientProviderError(ProviderError):
    """Timeout / 5xx-equivalent. Dispatch may retry with backoff."""


class PermanentProviderError(ProviderError):
    """Bad recipient / 4xx-equivalent. Dispatch marks FAILED without backoff."""


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

Editar [`app/providers/simulated.py`](app/providers/simulated.py). El archivo completo queda:

```python
"""In-process adapter. Logs a send; never talks to a vendor."""

from __future__ import annotations

import logging

from app.providers.port import (
    OutboundMessage,
    PermanentProviderError,
    TransientProviderError,
)

logger = logging.getLogger("app.providers.simulated")

_TRANSIENT_FAIL_TEMPLATE = "fail-transient"
_PERMANENT_FAIL_TEMPLATE = "fail-permanent"


class SimulatedNotificationProvider:
    """v1 channel adapter: succeeds unless the template is an exact fail switch."""

    def send(self, message: OutboundMessage) -> None:
        if message.template == _PERMANENT_FAIL_TEMPLATE:
            raise PermanentProviderError("simulated permanent failure")
        if message.template == _TRANSIENT_FAIL_TEMPLATE:
            raise TransientProviderError("simulated transient failure")
        logger.info(
            "simulated_send",
            extra={
                "channel": message.channel.value,
                "template": message.template,
            },
        )
```

Editar [`app/providers/__init__.py`](app/providers/__init__.py):

```python
"""Channel provider adapters. v1 ships a simulated adapter behind the port."""

from app.providers.port import (
    NotificationProvider,
    OutboundMessage,
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)
from app.providers.simulated import SimulatedNotificationProvider

__all__ = [
    "NotificationProvider",
    "OutboundMessage",
    "PermanentProviderError",
    "ProviderError",
    "SimulatedNotificationProvider",
    "TransientProviderError",
]
```

Editar [`tests/unit/providers/test_simulated.py`](tests/unit/providers/test_simulated.py). El archivo completo queda:

```python
import pytest

from app.domain.enums import Channel
from app.providers.port import (
    OutboundMessage,
    PermanentProviderError,
    TransientProviderError,
)
from app.providers.simulated import SimulatedNotificationProvider


def _message(template: str) -> OutboundMessage:
    return OutboundMessage(
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template=template,
        payload={"name": "Ada"},
    )


def test_simulated_send_returns_without_raising() -> None:
    SimulatedNotificationProvider().send(_message("welcome"))


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


def test_fail_transient_template_raises_transient() -> None:
    with pytest.raises(TransientProviderError):
        SimulatedNotificationProvider().send(_message("fail-transient"))


def test_fail_permanent_template_raises_permanent() -> None:
    with pytest.raises(PermanentProviderError):
        SimulatedNotificationProvider().send(_message("fail-permanent"))


def test_fail_prefix_is_not_enough() -> None:
    SimulatedNotificationProvider().send(_message("fail-transient-welcome"))
```

Cero sockets. Cero Twilio. Cero FastAPI.

- **Patrón:** puerto / adapter. El adapter **clasifica** el fallo; **no** decide el backoff.
- **Por qué templates exactos:** ejemplo: en curl pones `"template":"fail-transient"` y ves reintentos sin tocar código. Un `random` haría el demo irreproducible (Fase 9 lo prohibió por eso).
- **Alternativa descartada:** setting `SIMULATED_FAIL_MODE`. Enseñaría config, no el puerto; y cada test pelearía con el env global.
- **Capa:** `app/providers/`. Puede usar dominio (`Channel`). No puede importar `app.workers` ni `app.api`.

- **Commit (si EsrgaN autoriza):**

```text
feat: distinguish transient and permanent provider errors

Let the simulated adapter fail on exact templates so retries
can be demoed without a vendor SDK.
```

---

### Paso 10.3 — `DispatchService` reintenta o falla

Editar [`app/services/dispatch.py`](app/services/dispatch.py). El archivo completo queda:

```python
"""Use case: dispatch one persisted notification through a provider port."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from app.domain.enums import NotificationStatus
from app.domain.retry_policy import DeliveryRetryPolicy
from app.domain.state_machine import assert_transition
from app.models.notification import Notification
from app.providers.port import (
    NotificationProvider,
    OutboundMessage,
    PermanentProviderError,
)
from app.repositories.notification_repository import NotificationRepository

logger = logging.getLogger("app.dispatch")

_ERROR_MESSAGE_MAX = 512


class DispatchAction(StrEnum):
    SENT = "sent"
    SKIPPED = "skipped"
    MISSING = "missing"
    RETRY = "retry"
    FAILED = "failed"


@dataclass(frozen=True)
class DispatchResult:
    """What the worker task should do after this attempt. No Celery types here."""

    action: DispatchAction
    countdown_seconds: int | None = None
    dead_letter: bool = False


class DispatchService:
    def __init__(
        self,
        session: Session,
        repository: NotificationRepository,
        provider: NotificationProvider,
        policy: DeliveryRetryPolicy,
    ) -> None:
        self._session = session
        self._repository = repository
        self._provider = provider
        self._policy = policy

    def dispatch(self, notification_id: uuid.UUID) -> DispatchResult:
        """Load, skip terminals, PROCESSING → provider → SENT, RETRY, or FAILED. Commits here."""
        row = self._repository.get_by_id(notification_id)
        if row is None:
            logger.warning(
                "notification_dispatch_missing",
                extra={"notification_id": str(notification_id)},
            )
            return DispatchResult(DispatchAction.MISSING)

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
            return DispatchResult(DispatchAction.SKIPPED)

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
            return self._handle_send_failure(row, exc)

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
        return DispatchResult(DispatchAction.SENT)

    def _handle_send_failure(self, row: Notification, exc: Exception) -> DispatchResult:
        retryable = not isinstance(exc, PermanentProviderError)
        row.retry_count += 1
        row.error_message = str(exc)[:_ERROR_MESSAGE_MAX]
        extras = {
            "notification_id": str(row.id),
            "client_id": str(row.client_id),
            "channel": row.channel.value,
            "status": row.status.value,
            "retry_count": row.retry_count,
        }

        if self._policy.should_retry(row.retry_count, retryable=retryable):
            countdown = self._policy.countdown_for(row.retry_count)
            assert_transition(row.status, NotificationStatus.PENDING)
            row.status = NotificationStatus.PENDING
            self._session.commit()
            logger.info("notification_retry_scheduled", extra=extras)
            return DispatchResult(
                DispatchAction.RETRY,
                countdown_seconds=countdown,
            )

        assert_transition(row.status, NotificationStatus.FAILED)
        row.status = NotificationStatus.FAILED
        self._session.commit()
        logger.info("notification_dispatch_failed", extra=extras, exc_info=True)
        return DispatchResult(DispatchAction.FAILED, dead_letter=True)
```

El service ya devolvía `Notification` vía el repositorio (Fase 9). Importar el modelo aquí es idiomático. **Prohibido** importar `app.models` desde un **router**.

Editar [`tests/unit/services/test_dispatch_service.py`](tests/unit/services/test_dispatch_service.py). El archivo completo queda:

```python
from __future__ import annotations

import uuid

from app.domain.enums import Channel, NotificationStatus
from app.domain.retry_policy import DeliveryRetryPolicy
from app.models.notification import Notification
from app.providers.port import (
    OutboundMessage,
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)
from app.services.dispatch import DispatchAction, DispatchService


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


class TransientBoomProvider:
    def send(self, message: OutboundMessage) -> None:
        raise TransientProviderError("vendor 500")


class PermanentBoomProvider:
    def send(self, message: OutboundMessage) -> None:
        raise PermanentProviderError("bad recipient")


class UnclassifiedBoomProvider:
    def send(self, message: OutboundMessage) -> None:
        raise ProviderError("vendor 500")


class CrashProvider:
    def send(self, message: OutboundMessage) -> None:
        raise RuntimeError("socket exploded")


def _policy(*, max_attempts: int = 5) -> DeliveryRetryPolicy:
    return DeliveryRetryPolicy(max_attempts=max_attempts, countdown_seconds=(5, 15, 45))


def _row(
    *,
    status: NotificationStatus = NotificationStatus.PENDING,
    notification_id: uuid.UUID | None = None,
    retry_count: int = 0,
) -> Notification:
    return Notification(
        id=notification_id or uuid.uuid4(),
        client_id=uuid.uuid4(),
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={"n": 1},
        status=status,
        retry_count=retry_count,
    )


def _service(
    row: Notification | None,
    provider: object,
    session: FakeSession | None = None,
    *,
    max_attempts: int = 5,
) -> tuple[DispatchService, FakeSession]:
    sess = session or FakeSession()
    service = DispatchService(
        sess,
        FakeNotificationRepository(row),
        provider,  # type: ignore[arg-type]
        _policy(max_attempts=max_attempts),
    )
    return service, sess


def test_pending_becomes_sent_and_calls_provider_once() -> None:
    row = _row()
    provider = RecordingProvider()
    service, session = _service(row, provider)

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.SENT
    assert row.status is NotificationStatus.SENT
    assert row.sent_at is not None
    assert session.commit_calls == 2
    assert len(provider.messages) == 1


def test_already_sent_does_not_call_provider() -> None:
    row = _row(status=NotificationStatus.SENT)
    provider = RecordingProvider()
    service, session = _service(row, provider)

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.SKIPPED
    assert provider.messages == []
    assert session.commit_calls == 0
    assert row.status is NotificationStatus.SENT


def test_already_failed_does_not_call_provider() -> None:
    row = _row(status=NotificationStatus.FAILED)
    provider = RecordingProvider()
    service, session = _service(row, provider)

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.SKIPPED
    assert provider.messages == []
    assert session.commit_calls == 0


def test_processing_crash_recovery_sends_without_second_pending_transition() -> None:
    row = _row(status=NotificationStatus.PROCESSING)
    provider = RecordingProvider()
    service, session = _service(row, provider)

    service.dispatch(row.id)

    assert row.status is NotificationStatus.SENT
    assert session.commit_calls == 1
    assert len(provider.messages) == 1


def test_transient_error_returns_to_pending_with_countdown() -> None:
    row = _row()
    service, session = _service(row, TransientBoomProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.RETRY
    assert result.countdown_seconds == 5
    assert result.dead_letter is False
    assert row.status is NotificationStatus.PENDING
    assert row.retry_count == 1
    assert row.error_message == "vendor 500"
    assert row.sent_at is None
    assert session.commit_calls == 2


def test_unclassified_provider_error_is_retryable() -> None:
    row = _row()
    service, _session = _service(row, UnclassifiedBoomProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.RETRY
    assert row.status is NotificationStatus.PENDING


def test_unexpected_exception_is_retryable() -> None:
    row = _row()
    service, _session = _service(row, CrashProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.RETRY
    assert row.retry_count == 1
    assert row.status is NotificationStatus.PENDING


def test_permanent_error_fails_without_retry() -> None:
    row = _row()
    service, session = _service(row, PermanentBoomProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.FAILED
    assert result.dead_letter is True
    assert row.status is NotificationStatus.FAILED
    assert row.retry_count == 1
    assert row.error_message == "bad recipient"
    assert session.commit_calls == 2


def test_fifth_transient_failure_is_dead_lettered() -> None:
    row = _row(retry_count=4)
    service, _session = _service(row, TransientBoomProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.FAILED
    assert result.dead_letter is True
    assert row.retry_count == 5
    assert row.status is NotificationStatus.FAILED


def test_fourth_retry_uses_capped_countdown() -> None:
    row = _row(retry_count=3)
    service, _session = _service(row, TransientBoomProvider())

    result = service.dispatch(row.id)

    assert result.action is DispatchAction.RETRY
    assert result.countdown_seconds == 45
    assert row.retry_count == 4
    assert row.status is NotificationStatus.PENDING


def test_missing_row_is_a_noop() -> None:
    provider = RecordingProvider()
    service, session = _service(None, provider)

    result = service.dispatch(uuid.uuid4())

    assert result.action is DispatchAction.MISSING
    assert provider.messages == []
    assert session.commit_calls == 0
```

Si MyPy en tests no corre (`packages = ["app"]`), el `type: ignore[arg-type]` de `_service` es opcional: anota `provider` como `NotificationProvider`.

Editar [`tests/integration/test_dispatch.py`](tests/integration/test_dispatch.py). El archivo completo queda (Postgres real, provider fake, **cero** `sleep`, **cero** Celery vivo):

```python
import uuid

from sqlalchemy import Engine

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.domain.enums import Channel, NotificationStatus
from app.domain.retry_policy import DeliveryRetryPolicy
from app.models import Client, Notification
from app.providers.port import OutboundMessage, PermanentProviderError, TransientProviderError
from app.repositories.notification_repository import NotificationRepository
from app.services.dispatch import DispatchAction, DispatchService


class RecordingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, message: OutboundMessage) -> None:
        self.calls += 1


class FailOnceThenSucceed:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, message: OutboundMessage) -> None:
        self.calls += 1
        if self.calls == 1:
            raise TransientProviderError("once")


class AlwaysPermanent:
    def send(self, message: OutboundMessage) -> None:
        raise PermanentProviderError("nope")


def _policy() -> DeliveryRetryPolicy:
    return DeliveryRetryPolicy(max_attempts=5, countdown_seconds=(5, 15, 45))


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
                session,
                NotificationRepository(session),
                provider,
                _policy(),
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


def test_dispatch_retries_then_sends(persistence_engine: Engine) -> None:
    factory = create_session_factory(persistence_engine)
    provider = FailOnceThenSucceed()
    notification_id = uuid.uuid4()
    client_id: uuid.UUID
    with factory() as session:
        client = Client(
            name="dispatch-retry-it",
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
            first = DispatchService(
                session,
                NotificationRepository(session),
                provider,
                _policy(),
            ).dispatch(notification_id)
        assert first.action is DispatchAction.RETRY
        with factory() as session:
            row = session.get(Notification, notification_id)
            assert row is not None
            assert row.status is NotificationStatus.PENDING
            assert row.retry_count == 1
        with factory() as session:
            second = DispatchService(
                session,
                NotificationRepository(session),
                provider,
                _policy(),
            ).dispatch(notification_id)
        assert second.action is DispatchAction.SENT
        with factory() as session:
            row = session.get(Notification, notification_id)
            assert row is not None
            assert row.status is NotificationStatus.SENT
            assert row.sent_at is not None
        assert provider.calls == 2
    finally:
        with factory() as session:
            session.delete(session.get(Notification, notification_id))
            session.delete(session.get(Client, client_id))
            session.commit()


def test_dispatch_permanent_failure_stays_failed(persistence_engine: Engine) -> None:
    factory = create_session_factory(persistence_engine)
    provider = AlwaysPermanent()
    notification_id = uuid.uuid4()
    client_id: uuid.UUID
    with factory() as session:
        client = Client(
            name="dispatch-perm-it",
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
            result = DispatchService(
                session,
                NotificationRepository(session),
                provider,
                _policy(),
            ).dispatch(notification_id)
        assert result.action is DispatchAction.FAILED
        assert result.dead_letter is True
        with factory() as session:
            row = session.get(Notification, notification_id)
            assert row is not None
            assert row.status is NotificationStatus.FAILED
            assert row.retry_count == 1
            assert row.sent_at is None
    finally:
        with factory() as session:
            session.delete(session.get(Notification, notification_id))
            session.delete(session.get(Client, client_id))
            session.commit()
```

- **Patrón:** application service + state machine + resultado explícito (no excepción Celery en el use case).
- **Por qué `PROCESSING → PENDING`:** ejemplo: `GET /status` durante los 15 s de espera enseña “sigue en cola”, no “se rompió”. Si te quedaras en `PROCESSING`, un cliente pensaría que el email está saliendo ahora mismo.
- **Alternativa descartada:** `raise self.retry()` **dentro** de `DispatchService`. El servicio importaría Celery y los unit tests necesitarían un worker. El charter: retry policy en worker/task; la **decisión** (sí/no + segundos) es de dominio/servicio.
- **Capa:** `app/services/`. No importa `app.workers` ni routers.

- **Commit (si EsrgaN autoriza):**

```text
feat: retry transient dispatch failures with backoff

Return PENDING plus a countdown so the worker can reschedule
without the application service importing Celery.
```

---

### Paso 10.4 — Celery `bind=True`, retry y DLQ

Editar [`app/workers/celery_app.py`](app/workers/celery_app.py). Cambia **solo** `task_queues`:

```python
    task_queues=(
        Queue("notifications"),
        Queue("notifications.dlq"),
    ),
```

El resto del `conf.update` **no se toca** (`task_acks_late=True`, JSON, sin result backend, default queue `notifications`).

Editar [`app/workers/tasks.py`](app/workers/tasks.py). El archivo completo queda:

```python
"""Celery tasks. Payloads are ids; work lives in DispatchService."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.domain.retry_policy import DeliveryRetryPolicy
from app.providers.simulated import SimulatedNotificationProvider
from app.repositories.notification_repository import NotificationRepository
from app.services.dispatch import DispatchAction, DispatchResult, DispatchService
from app.workers.celery_app import celery_app
from app.workers.runtime import get_worker_session_factory

logger = logging.getLogger("app.workers.tasks")


@celery_app.task(name="notifications.dead_letter", ignore_result=True, max_retries=0)  # type: ignore[untyped-decorator]
def record_dead_letter(notification_id: str) -> None:
    """Log a failed id for inspection. Never call a provider."""
    logger.warning(
        "notification_dead_lettered",
        extra={"notification_id": notification_id},
    )


def apply_delivery_result(
    task: Any,
    result: DispatchResult,
    notification_id: str,
    *,
    max_retries: int,
    publish_dead_letter: Callable[..., Any] | None = None,
) -> None:
    """Map a DispatchResult onto Celery retry or the DLQ. Tested without a live worker."""
    if result.action is DispatchAction.RETRY:
        countdown = result.countdown_seconds if result.countdown_seconds is not None else 5
        raise task.retry(countdown=countdown, max_retries=max_retries)
    if result.dead_letter:
        publish = publish_dead_letter
        if publish is None:
            publish = record_dead_letter.apply_async
        try:
            publish(args=[notification_id], queue="notifications.dlq")
        except Exception:
            logger.exception(
                "notification_dlq_publish_failed",
                extra={"notification_id": notification_id},
            )


@celery_app.task(bind=True, name="notifications.deliver", ignore_result=True)  # type: ignore[untyped-decorator]
def deliver_notification(self: Any, notification_id: str) -> None:
    """Load the row and dispatch. Never import FastAPI routers."""
    settings = get_settings()
    policy = DeliveryRetryPolicy(
        max_attempts=settings.max_delivery_attempts,
        countdown_seconds=settings.delivery_retry_countdowns,
    )
    result: DispatchResult | None = None
    factory = get_worker_session_factory()
    session = factory()
    try:
        service = DispatchService(
            session=session,
            repository=NotificationRepository(session),
            provider=SimulatedNotificationProvider(),
            policy=policy,
        )
        result = service.dispatch(uuid.UUID(notification_id))
    finally:
        session.close()
    if result is not None:
        apply_delivery_result(
            self,
            result,
            notification_id,
            max_retries=settings.max_delivery_attempts - 1,
        )
```

Editar [`app/workers/__init__.py`](app/workers/__init__.py):

```python
"""Celery workers. Tasks receive notification ids; retries and DLQ live here."""
```

**No** crear `tests/unit/workers/__init__.py` (pytest usa `importlib`). Crear [`tests/unit/workers/test_apply_delivery_result.py`](tests/unit/workers/test_apply_delivery_result.py):

```python
from __future__ import annotations

import pytest

from app.services.dispatch import DispatchAction, DispatchResult
from app.workers.tasks import apply_delivery_result


class FakeRetry(Exception):
    def __init__(self, countdown: int, max_retries: int) -> None:
        self.countdown = countdown
        self.max_retries = max_retries


class FakeTask:
    def retry(self, countdown: int, max_retries: int) -> None:
        raise FakeRetry(countdown, max_retries)


def test_retry_result_raises_task_retry() -> None:
    with pytest.raises(FakeRetry) as exc_info:
        apply_delivery_result(
            FakeTask(),
            DispatchResult(DispatchAction.RETRY, countdown_seconds=15),
            "nid",
            max_retries=4,
        )
    assert exc_info.value.countdown == 15
    assert exc_info.value.max_retries == 4


def test_failed_result_publishes_to_dlq_queue() -> None:
    seen: dict[str, object] = {}

    def fake_publish(*, args: list[str], queue: str) -> None:
        seen["args"] = args
        seen["queue"] = queue

    apply_delivery_result(
        FakeTask(),
        DispatchResult(DispatchAction.FAILED, dead_letter=True),
        "nid-1",
        max_retries=4,
        publish_dead_letter=fake_publish,
    )
    assert seen["args"] == ["nid-1"]
    assert seen["queue"] == "notifications.dlq"


def test_sent_result_is_a_noop() -> None:
    def boom(*, args: list[str], queue: str) -> None:
        raise AssertionError("DLQ must not run on SENT")

    apply_delivery_result(
        FakeTask(),
        DispatchResult(DispatchAction.SENT),
        "nid",
        max_retries=4,
        publish_dead_letter=boom,
    )


def test_dlq_publish_failure_is_logged_not_raised() -> None:
    def boom(*, args: list[str], queue: str) -> None:
        raise ConnectionError("broker down")

    apply_delivery_result(
        FakeTask(),
        DispatchResult(DispatchAction.FAILED, dead_letter=True),
        "nid",
        max_retries=4,
        publish_dead_letter=boom,
    )
```

[`tests/unit/test_celery_queue.py`](tests/unit/test_celery_queue.py) **no se toca**: el accept path sigue publicando solo a `notifications`.

Cero worker vivo. Cero `task_always_eager`. Cero `time.sleep`.

- **Patrón:** task tonta + función pura `apply_delivery_result` (fácil de testear) + cola nombrada DLQ.
- **Por qué Redis no “trae DLQ de fábrica”:** ejemplo: RabbitMQ tiene *dead-letter exchange*. Redis-as-broker no. Nosotros **publicamos** a una cola con nombre, como un segundo rail de tickets rotos. Eso es una convención del proyecto, no magia de Celery.
- **Por qué `max_retries=max_attempts - 1`:** Celery cuenta *reintentos*, no el intento inicial. 1 + 4 = 5. El presupuesto **real** sigue siendo Postgres `retry_count` vs `max_delivery_attempts` (D4). Celery es el cinturón.
- **Alternativa descartada:** `task_always_eager=True` para “probar retries”. Rompería los tests HTTP de `PENDING` y enseñaría un modo que **no** usamos en local.
- **Capa:** `app/workers/`. No importa routers. `DispatchService` no importa este módulo.

- **Commit (si EsrgaN autoriza):**

```text
feat: reschedule transient failures and publish exhausted ids to DLQ

Keep Celery on countdown retries and a named notifications.dlq
queue so failed work is inspectable without an admin UI.
```

---

### Paso 10.5 — README + STATUS (STATUS solo al cerrar el código)

Editar [`README.md`](README.md) **en la implementación**:

- Status: “Phase 10: retries 5s/15s/45s (cap 45s), max 5 attempts, `FAILED` + queue `notifications.dlq`”.
- Worker:

```bash
celery -A app.workers.celery_app worker --loglevel=INFO --queues=notifications,notifications.dlq
```

- Después del curl feliz (`template: welcome` → poll `SENT`), documentar los dos demos:

```bash
# Transient: worker retries (5s, 15s, 45s, 45s) then FAILED + DLQ log
curl -i -H "X-API-Key: PASTE_RAW_KEY" -H "Content-Type: application/json" \
  -d '{"channel":"email","recipient":"user@example.com","template":"fail-transient"}' \
  http://127.0.0.1:8000/api/v1/notifications/send
# poll GET /status: PENDING between attempts, then FAILED
# GET /metrics → failed increments only after FAILED

# Permanent: FAILED on the first attempt, no 5s wait
curl -i -H "X-API-Key: PASTE_RAW_KEY" -H "Content-Type: application/json" \
  -d '{"channel":"email","recipient":"nobody@example.com","template":"fail-permanent"}' \
  http://127.0.0.1:8000/api/v1/notifications/send
```

- `.env`: `MAX_DELIVERY_ATTEMPTS=5`, `DELIVERY_RETRY_COUNTDOWNS=5,15,45`.
- Dejar claro: pytest **no** espera el backoff. Docker sigue “fase posterior”. Beat / replay admin / Twilio **no** están.
- El diagrama mermaid **ya** tiene caja DLQ: quita la frase “the DLQ box is the target shape, not this phase” y di que la DLQ es la cola `notifications.dlq` (inspección por log + fila `FAILED`).

Si existe [`docs/EXPLANATIONS.md`](docs/EXPLANATIONS.md) en la máquina de EsrgaN, **enriquece** (retries, transiente vs permanente, por qué Redis no tiene DLX). **Nunca** lo commitees (`.gitignore`).

Editar [`docs/STATUS.md`](docs/STATUS.md) **solo al cerrar la implementación** (otro turno). Este turno de PLAN **no** marca Fase 10 hecha. Cuando el código exista:

- Marcar Fase 10 hecha: backoff 5/15/45 (tope 45), 5 intentos, `PROCESSING → PENDING` en retry, `FAILED` + `notifications.dlq`.
- Decir qué **sigue**: Fase 11 = README / curl polish (runbook local). No Compose.
- “Qué no existe” **deja de listar** retries/DLQ. Sigue incluyendo Beat, replay admin, Docker, mapper de `InvalidStatusTransition`, Mailtrap/Twilio reales.
- No marcar Fase 11 como hecha.

- **Commit (si EsrgaN autoriza):**

```text
docs: record retries, DLQ, and simulated fail templates
```

---

## 4. Checklist de cierre

- [ ] `pytest -q` verde (105 anteriores adaptados + policy + config CSV + simulado fail + dispatch retry/permanente/agotado + apply_delivery_result + integración transiente→SENT y permanente→FAILED)
- [ ] `ruff check app tests` limpio; `mypy app` limpio
- [ ] `app/domain/` sigue sin importar FastAPI/SQLAlchemy/Redis/Celery/Pydantic
- [ ] Routers **no** importan `app.workers` ni providers; `NotificationService.accept` intacto
- [ ] Worker **no** importa `app.api.routers`; `DispatchService` **no** importa Celery
- [ ] Cero `create_all`, cero migración nueva, cero `commit` en `get_db`
- [ ] HTTP test env: `POST /send` sigue 202 `PENDING` e `InMemoryNotificationQueue`
- [ ] Transiente: `PENDING` + `retry_count++` + countdown 5/15/45/45; 5.º fallo → `FAILED` + `dead_letter`
- [ ] Permanente: `FAILED` en el primer golpe, sin countdown
- [ ] `ProviderError` pelado y `RuntimeError` son **reintentables** (los tests viejos de FAILED inmediato están **reescritos**)
- [ ] Skip `SENT`/`FAILED`; missing noop; recovery desde `PROCESSING`
- [ ] DLQ publish a queue `notifications.dlq` con `str(id)`; fallo de publish se loguea, no revienta
- [ ] `GET /health` sigue 200 sin API key y sin I/O a Redis/Celery
- [ ] Token Bucket intacto (índice 0); broker índice 1
- [ ] Cero `time.sleep`, cero worker vivo en pytest, cero `task_always_eager` global, cero Twilio, cero JWT, cero Docker, cero Beat
- [ ] README: worker con ambas colas; curl `fail-transient` / `fail-permanent`
- [ ] 3–6 learning points en español **simple** para EsrgaN (retry vs permanente, backoff con tope, por qué PENDING otra vez, por qué DLQ es una cola nombrada y no magia de Redis, por qué el servicio no importa Celery, por qué 5 intentos = `max_retries` Celery 4)
- [ ] Commits hechos o mensajes esperando a EsrgaN

**Prohibido al terminar:** Beat, `import twilio`, Compose, mapper HTTP de transiciones, `BackgroundTasks`, eager por defecto, 135 s de espera, UI de replay.

---

## 5. Qué sigue (no implementar)

Siguiente `PLAN.md` (otra reescritura): **README / curl polish** (runbook local, Fase 11). Esta fase ya deja retries + DLQ. No implementar README “de portfolio”, Compose, Beat ni providers reales en este turno.
