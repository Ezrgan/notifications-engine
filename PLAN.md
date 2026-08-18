# PLAN.md — Fase 6: Accept send (`PENDING` + puerto de cola + `202`)

> **REGLA OBLIGATORIA PARA TODOS LOS AGENTES:**
> Antes de ejecutar cualquier paso, leer y acatar [`AGENTS.md`](./AGENTS.md), [`.cursor/rules/`](./.cursor/rules/) (sobre todo `fastapi.mdc`, `postgresql.mdc`, `testing.mdc` y `celery.mdc`) y [`docs/HOW_TO_WRITE_THE_NEXT_PLAN.md`](./docs/HOW_TO_WRITE_THE_NEXT_PLAN.md).
> Este archivo es el **único plan ejecutable**. Describe **una sola fase**. Cuando cierre, EsrgaN **reescribe** `PLAN.md` entero (ver el playbook en `docs/`).
> No implementar Celery real, Redis, Token Bucket, métricas, mapper de `InvalidStatusTransition`, JWT, Mailtrap/Twilio ni Docker.

> **Cómo está pensado este documento:**
> Un agente debe poder implementarlo **sin inventar**. Cada paso: archivos exactos, contrato, tests, commit propuesto, qué no tocar.
> Código completo. Cero placeholders. Cero `# ... rest of code ...`.
> Enseñar a EsrgaN en **español simple**, con ejemplos. Sin jerga sin definir.

> **Estado de partida (verificado):**
> Rama actual `feat/phase-5-api-keys` = `f6a5058` (`feat: authenticate machine clients with X-API-Key`).
> `origin/main` = `be14f38` — squash del PR **#5** (Fase 4). **Fase 5 aún no está en `main`.**
> `pytest -q` → **44 passed**. `ruff check app tests` limpio.
> Hay `X-API-Key`, `ClientRepository`, `GET /api/v1/clients/me`, tablas `clients` / `notifications` (Alembic `a1b2c3d4e5f6`), índice único parcial `(client_id, idempotency_key)`.
> **No** existe `POST /send`, `NotificationRepository`, `NotificationService`, puerto de cola, Celery, Redis, ni `GET /metrics`. `app/services/__init__.py` y `app/workers/__init__.py` son solo docstrings.

---

## 0. Decisiones congeladas (esta fase)

| # | Decisión | Valor congelado |
| --- | --- | --- |
| D1 | Idea de la fase | El cliente autenticado **acepta** un envío: validar body → persistir `PENDING` → `enqueue(notification_id)` en un **puerto** → **`202 Accepted`**. Nadie llama a un provider. Nadie arranca Celery. |
| D2 | Por qué un puerto y no Celery ahora | Un **puerto** es una interfaz que *nosotros* definimos (`enqueue(id)`). Un **adaptador** es la implementación (hoy: lista en RAM; Fase 9: Celery). Ejemplo: el servicio dice “pon este UUID en la cola”; no sabe si detrás hay Redis o un array de pytest. Si importáramos Celery hoy, el HTTP path se casaría con el broker antes de tener worker. |
| D3 | Adaptador de esta fase | `InMemoryNotificationQueue`: guarda UUIDs en una `list`. Vive en `app.state` (lifespan). Se pierde al reiniciar el proceso. **Eso es correcto:** las filas `PENDING` quedan en Postgres; el worker (Fase 9) será quien las despache. |
| D4 | Orden persistir vs encolar | **`commit` primero, luego `enqueue`.** Ejemplo: si el proceso muere después del `202`, la fila ya existe y se puede consultar. Si `enqueue` falla, HTTP **503** y la fila sigue `PENDING` (hueco conocido: no hay *transactional outbox*; no lo construyas). |
| D5 | Replay de idempotencia | Misma `client_id` + misma `idempotency_key` → devolver la fila **original** con **202** (no 409, no 200). **No** volver a `enqueue`. Ejemplo: el checkout reintenta el POST porque no vio la respuesta; no queremos dos SMS. |
| D6 | Carrera (dos POSTs a la vez) | El índice único `uq_notifications_client_idempotency` es la red de seguridad. Si `commit` lanza `IntegrityError`, `rollback`, buscar la fila ganadora, devolverla, **no** encolar. Si el error no es de idempotencia (no hay key / no hay fila), **re-lanzar**. |
| D7 | `idempotency_key` | Campo **opcional del body** (no header). `str` 1–128 o `null`/omitido. Dos POST **sin** key = dos filas (aunque el body sea igual). Key vacía `""` → **422**. |
| D8 | HTTP send | `POST /api/v1/notifications/send` + `X-API-Key`. **202** `{"notification_id": "<uuid>", "status": "PENDING"}`. Auth rota → **401** idéntico a `/me`. Body inválido → **422** de Pydantic (no reescribir el schema de error 422). |
| D9 | HTTP status (misma fase) | `GET /api/v1/notifications/{notification_id}/status`. Respuesta `{"notification_id": "...", "status": "PENDING\|PROCESSING\|SENT\|FAILED"}`. Sin fila **o** fila de otro cliente → **404** con el **mismo** cuerpo (no filtrar “existe pero no es tuya”). No está en §10.1 como fase aparte; es la lectura del mismo agregado. **No** es métricas. |
| D10 | 404 / 503 | `NotificationNotFound` (dominio) → `{"detail": "Notification not found", "code": "not_found"}`. `QueueUnavailableError` vive **junto al puerto** (`app/services/queue.py`), no en `app/api/errors.py`: el servicio no puede importar la capa HTTP. Handler → `{"detail": "Queue unavailable", "code": "service_unavailable"}`. **No** mapear `InvalidStatusTransition` (esta fase no transiciona; inserta `PENDING` de entrada). |
| D11 | Validación del body | `channel`: `email` / `sms` / `push` / `webhook` (valores del `StrEnum`, minúsculas). `recipient`: 1–320 chars, **sin** regex de email ni E.164. `template`: 1–128. `payload`: objeto JSON, default `{}`. `extra="forbid"`. `"EMAIL"` (mayúsculas) → 422. |
| D12 | Capas | Router → schemas + `Depends` + `NotificationService`. Servicio → repositorio + puerto de cola + `session.commit()`. Repositorio → SQLAlchemy. Router **no** importa `app.models` ni `Session`. Dominio **no** importa FastAPI/SQLAlchemy/Pydantic. |
| D13 | `get_db` | Sigue **sin** `commit` (Fase 5). El use case commitea. `expire_on_commit=False` ya está en `create_session_factory`: tras `commit` puedes leer `notification.id`. |
| D14 | UUID | El servicio (o el `create` del repo) asigna `id=uuid.uuid4()` **antes** del commit para poder encolar el mismo id. No esperes a que Postgres lo genere. |
| D15 | Settings / Alembic / libs | **Cero** campo nuevo. **Cero** revisión Alembic (la tabla ya existe). **Cero** `celery`, `redis`, `kombu` en `pyproject.toml`. `REDIS_URL` sigue comentado en `.env.example`. |
| D16 | Fuera de esta fase | Celery worker, provider simulado, retries/DLQ, Token Bucket/429, `GET /metrics`, alta HTTP de clientes, `BackgroundTasks`, JWT, Docker, outbox table. |
| D17 | Tests | Unitarios: puerto in-memory, schemas, servicio con **fakes** (sin Postgres). Integración: repo con `db_session` (rollback); HTTP con filas **commiteadas** + `TestClient` (otro pool, igual que auth). Cero `time.sleep`. Cero SQLite. Cero Twilio. |
| D18 | Logs | `notification_accepted` / `notification_idempotent_replay` / `notification_status_read` con `notification_id`, `client_id`, `channel`, `status`. **Nunca** payload completo, recipient entero, ni API key. |
| D19 | Git | Rama `feat/phase-6-accept-send` **desde** `feat/phase-5-api-keys` (`f6a5058`), **no** desde `main` (`be14f38` no tiene auth). Si EsrgaN fusiona Fase 5 a `main` antes, entonces sí partir de ese `main` nuevo. Commits **solo si EsrgaN lo pide**. |
| D20 | Docker / extras | Prohibidos. No Kafka, JWT, Prisma, Redis, Celery, Compose. |

---

## 1. Diagnóstico (por qué esta fase)

Archivos reales, no memoria:

1. [`docs/STATUS.md`](docs/STATUS.md) marca Fases 1–5 hechas en código. [`AGENTS.md`](AGENTS.md) §10.1 siguiente número libre = **6 Accept send**. No saltar a métricas (7), Redis (8) ni Celery (9): encolar en un broker que nadie consume no enseña el contrato HTTP `202`.
2. [`app/models/notification.py`](app/models/notification.py) ya tiene columnas, default `PENDING` e índice único parcial. [`tests/integration/test_persistence.py`](tests/integration/test_persistence.py) inserta filas a mano. Eso **no** es el caso de uso: falta el puente HTTP → servicio → repo → puerto.
3. [`app/api/deps.py`](app/api/deps.py) ya resuelve `X-API-Key` a `AuthenticatedClient`. [`app/main.py`](app/main.py) solo monta health + `/clients/me`. [`app/services/__init__.py`](app/services/__init__.py) está vacío. [`pyproject.toml`](pyproject.toml) no lista Celery ni Redis.
4. [`app/core/db.py`](app/core/db.py) ya tiene `expire_on_commit=False`. [`get_db`](app/api/deps.py) no commitea. El unique de idempotencia ya está en Alembic `a1b2c3d4e5f6`. Esta fase **no** toca migraciones.
5. Ejemplo de uso: `curl -H 'X-API-Key: ne_…' -d '{"channel":"email","recipient":"a@b.com","template":"welcome"}' POST /api/v1/notifications/send` → `202` + UUID. Un `GET …/status` con esa key ve `PENDING`. Otra app con otra key y el mismo UUID ve `404`. El SMS **no** sale: solo se aceptó el trabajo.

---

## 2. Árbol al cerrar esta fase

```text
app/domain/exceptions.py                      # EDITAR: NotificationNotFound
app/domain/__init__.py                        # EDITAR: reexportar NotificationNotFound
app/services/queue.py                         # NUEVO: Protocol + InMemory + QueueUnavailableError
app/services/notification_service.py          # NUEVO: accept + get_status
app/services/__init__.py                      # EDITAR: reexportar servicio/puerto
app/repositories/notification_repository.py   # NUEVO
app/repositories/__init__.py                  # EDITAR: reexportar NotificationRepository
app/schemas/notification.py                   # NUEVO: request + responses
app/api/errors.py                             # no tocar (sigue solo UnauthorizedError)
app/api/deps.py                               # EDITAR: get_notification_queue, get_notification_service
app/api/routers/notifications.py              # NUEVO: POST /send + GET /{id}/status
app/main.py                                   # EDITAR: lifespan queue, handlers 404/503, include_router
tests/unit/test_queue.py                      # NUEVO
tests/unit/schemas/test_notification.py       # NUEVO
tests/unit/services/test_notification_service.py  # NUEVO (fakes, sin Postgres)
tests/integration/test_notification_repository.py # NUEVO (rollback session)
tests/integration/test_send.py                # NUEVO (filas commiteadas + TestClient)
tests/integration/conftest.py                 # EDITAR: borrar notifications antes del client (FK RESTRICT)
README.md                                     # EDITAR: curl send + status
docs/STATUS.md                                # EDITAR en el último paso de implementación
```

**No crear:** `celery_app.py`, `tasks.py`, `app/providers/*` reales, `Dockerfile`, `docker-compose.yml`, revisión Alembic, `GET /metrics`, Redis client, `BackgroundTasks`, outbox table, `ClientService`.

**No tocar:** máquina de estados (no hay transiciones aquí), modelos/columnas, `GET /health`, `SECRET_KEY` / `DATABASE_URL`, `hash_api_key`, `create_all`, `pyproject.toml` dependencies.

---

## 3. Git

Fase 5 vive en `feat/phase-5-api-keys` (`f6a5058`), **no** en `origin/main`. Crear la rama de Fase 6 así:

```bash
git checkout feat/phase-5-api-keys
# HEAD esperado: f6a5058
git checkout -b feat/phase-6-accept-send
```

Si EsrgaN ya fusionó Fase 5 a `main`, partir de ese `main` actualizado. **Nunca** partir de `be14f38`.

Antes de cerrar cada paso de código:

```bash
source .venv/bin/activate
pytest -q
ruff check app tests
```

Los 44 tests de Fases 2–5 deben seguir verdes (más los nuevos de esta fase).

---

## FASE 0 — Preparación

- [ ] `pytest -q` → 44 passed **antes** de editar
- [ ] `ruff check app tests` limpio
- [ ] Postgres local sigue arriba (`psql -d notifications_engine_test -c 'SELECT 1'`)
- [ ] Rama `feat/phase-6-accept-send` creada desde `feat/phase-5-api-keys` (`f6a5058`), no desde `main` antiguo
- [ ] Cero Docker, cero `uv pip install celery` / `redis`
- [ ] Enseñar a EsrgaN (ejemplo): **aceptar** no es **enviar**. Es como dejar un sobre en bandeja de salida: te dan un número de seguimiento (`notification_id`) y `202` (“lo tomé; aún no lo despaché”). Celery sería el cartero; llega en Fase 9.

---

## FASE 6 — Accept send

### Paso 6.1 — Puerto de cola (Protocol + in-memory)

Crear [`app/services/queue.py`](app/services/queue.py). Responsabilidad única: definir *qué* significa encolar un id, y un adaptador de proceso para tests y local. Quién lo llama: `NotificationService` y el lifespan. El router **no** lo llama. **No** vive en `app/workers/` (el API no debe importar workers).

```python
"""Queue port for accepted notifications.

The HTTP path enqueues an id; it never talks to Celery or a provider.
InMemoryNotificationQueue is the v1 adapter until a later phase swaps Celery in.
"""

from __future__ import annotations

import uuid
from typing import Protocol


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
```

Crear [`tests/unit/test_queue.py`](tests/unit/test_queue.py):

```python
import uuid

from app.services.queue import InMemoryNotificationQueue


def test_in_memory_queue_records_ids_in_order() -> None:
    queue = InMemoryNotificationQueue()
    first = uuid.uuid4()
    second = uuid.uuid4()
    queue.enqueue(first)
    queue.enqueue(second)
    assert queue.enqueued == [first, second]


def test_in_memory_queue_starts_empty() -> None:
    assert InMemoryNotificationQueue().enqueued == []
```

- **Patrón:** puerto / adaptador (hexagonal). El Protocol es el enchufe; InMemory es un ladrón de prueba.
- **Por qué en este servicio:** ejemplo: mañana `CeleryNotificationQueue.enqueue` hace `deliver.delay(str(id))`. `NotificationService.accept` **no cambia**.
- **Alternativa descartada:** `BackgroundTasks` de FastAPI. Si Uvicorn muere, la tarea se pierde y no hay fila-con-worker. `AGENTS.md` lo prohíbe para trabajo que debe sobrevivir.
- **Capa:** `app/services/`. No es dominio (el dominio no sabe qué es una cola). No es `app/workers/` (aún no hay Celery).

- **Commit (si EsrgaN autoriza):**

```text
feat: add an in-memory notification queue port

Keep accept-send independent of Celery so the HTTP path
enqueues ids behind a stable interface.
```

---

### Paso 6.2 — `NotificationRepository`

Crear [`app/repositories/notification_repository.py`](app/repositories/notification_repository.py). Responsabilidad única: insertar y buscar notificaciones. Quién lo llama: `NotificationService`. El router **no** lo llama.

```python
"""Data access for Notification rows. Routers must not query Session themselves."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import Channel, NotificationStatus
from app.models.notification import Notification


class NotificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        client_id: uuid.UUID,
        channel: Channel,
        recipient: str,
        template: str,
        payload: dict[str, Any],
        idempotency_key: str | None,
    ) -> Notification:
        """Add a PENDING row with a client-side UUID. Caller commits."""
        row = Notification(
            id=uuid.uuid4(),
            client_id=client_id,
            channel=channel,
            recipient=recipient,
            template=template,
            payload=payload,
            status=NotificationStatus.PENDING,
            idempotency_key=idempotency_key,
        )
        self._session.add(row)
        return row

    def get_by_id_for_client(
        self,
        notification_id: uuid.UUID,
        client_id: uuid.UUID,
    ) -> Notification | None:
        """Return the row only if it belongs to ``client_id``."""
        return self._session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.client_id == client_id,
            )
        )

    def get_by_idempotency_key(
        self,
        client_id: uuid.UUID,
        idempotency_key: str,
    ) -> Notification | None:
        """Return the existing row for this client+key, or None."""
        return self._session.scalar(
            select(Notification).where(
                Notification.client_id == client_id,
                Notification.idempotency_key == idempotency_key,
            )
        )
```

**Prohibido:** `get_by_id` sin `client_id` en esta fase (invitaría a filtrar existencia entre clientes). El worker (Fase 9) podrá añadir un lookup interno.

Editar [`app/repositories/__init__.py`](app/repositories/__init__.py):

```python
"""Persistence adapters: repository implementations."""

from app.repositories.client_repository import ClientRepository
from app.repositories.notification_repository import NotificationRepository

__all__ = ["ClientRepository", "NotificationRepository"]
```

Crear [`tests/integration/test_notification_repository.py`](tests/integration/test_notification_repository.py) con el `db_session` de rollback (aquí no hay HTTP):

```python
import uuid

from sqlalchemy.orm import Session

from app.domain.enums import Channel, NotificationStatus
from app.models import Client
from app.repositories import NotificationRepository


def _client(session: Session) -> Client:
    row = Client(
        name="checkout-app",
        hashed_api_key=f"dummy-hash-{uuid.uuid4().hex}",
        is_active=True,
    )
    session.add(row)
    session.flush()
    return row


def test_create_inserts_pending_row(db_session: Session) -> None:
    client = _client(db_session)
    repo = NotificationRepository(db_session)
    row = repo.create(
        client_id=client.id,
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={"x": 1},
        idempotency_key=None,
    )
    db_session.flush()
    assert row.status is NotificationStatus.PENDING
    assert row.payload["x"] == 1
    assert row.id is not None


def test_get_by_id_for_client_hides_other_clients_row(db_session: Session) -> None:
    owner = _client(db_session)
    other = _client(db_session)
    repo = NotificationRepository(db_session)
    row = repo.create(
        client_id=owner.id,
        channel=Channel.SMS,
        recipient="+15551234567",
        template="otp",
        payload={},
        idempotency_key="k1",
    )
    db_session.flush()
    assert repo.get_by_id_for_client(row.id, owner.id) is not None
    assert repo.get_by_id_for_client(row.id, other.id) is None
    assert repo.get_by_idempotency_key(owner.id, "k1") is not None
    assert repo.get_by_idempotency_key(other.id, "k1") is None
```

- **Patrón:** repository. La query con `client_id` **es** la regla de autorización de lectura.
- **Por qué:** ejemplo: si el status hiciera `WHERE id = :id` sin cliente, una app podría enumerar UUIDs ajenos. El 404 uniforme sale de “no hay fila **para ti**”.
- **Alternativa descartada:** `session.execute` en el servicio. Duplicarías el `WHERE` en accept y en status.
- **Capa:** `app/repositories/`. Puede importar modelos. **No** puede importar FastAPI.

- **Commit (si EsrgaN autoriza):**

```text
feat: add NotificationRepository for pending inserts

Scope lookups by client_id so status reads cannot leak
another app's notifications.
```

---

### Paso 6.3 — Schemas Pydantic v2

Crear [`app/schemas/notification.py`](app/schemas/notification.py). Responsabilidad: contrato HTTP de send/status. Quién lo usa: router y servicio (el servicio **devuelve** estos schemas, no modelos ORM).

```python
"""Pydantic v2 schemas for notification accept and status."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Channel, NotificationStatus


class SendNotificationRequest(BaseModel):
    """Body for POST /send. extra=forbid so typos fail 422 instead of being dropped."""

    model_config = ConfigDict(extra="forbid")

    channel: Channel
    recipient: str = Field(min_length=1, max_length=320)
    template: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class SendAcceptedResponse(BaseModel):
    notification_id: uuid.UUID
    status: NotificationStatus


class NotificationStatusResponse(BaseModel):
    notification_id: uuid.UUID
    status: NotificationStatus
```

Crear [`tests/unit/schemas/test_notification.py`](tests/unit/schemas/test_notification.py):

```python
import pytest
from pydantic import ValidationError

from app.domain.enums import Channel
from app.schemas.notification import SendNotificationRequest


def test_send_request_accepts_minimal_email_body() -> None:
    body = SendNotificationRequest.model_validate(
        {
            "channel": "email",
            "recipient": "user@example.com",
            "template": "welcome",
        }
    )
    assert body.channel is Channel.EMAIL
    assert body.payload == {}
    assert body.idempotency_key is None


def test_send_request_rejects_unknown_channel() -> None:
    with pytest.raises(ValidationError):
        SendNotificationRequest.model_validate(
            {
                "channel": "fax",
                "recipient": "user@example.com",
                "template": "welcome",
            }
        )


def test_send_request_rejects_uppercase_channel_token() -> None:
    with pytest.raises(ValidationError):
        SendNotificationRequest.model_validate(
            {
                "channel": "EMAIL",
                "recipient": "user@example.com",
                "template": "welcome",
            }
        )


def test_send_request_rejects_empty_recipient() -> None:
    with pytest.raises(ValidationError):
        SendNotificationRequest.model_validate(
            {
                "channel": "sms",
                "recipient": "",
                "template": "otp",
            }
        )


def test_send_request_rejects_empty_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        SendNotificationRequest.model_validate(
            {
                "channel": "email",
                "recipient": "user@example.com",
                "template": "welcome",
                "idempotency_key": "",
            }
        )


def test_send_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SendNotificationRequest.model_validate(
            {
                "channel": "email",
                "recipient": "user@example.com",
                "template": "welcome",
                "from": "nope",
            }
        )
```

- **Patrón:** DTO de borde HTTP (Pydantic v2 `ConfigDict`, no `class Config`).
- **Por qué `extra="forbid"`:** ejemplo: el cliente manda `"chanel"` (typo). Sin forbid, Pydantic lo tira y tú persistes un body incompleto o ignoras el error. Con forbid, **422** inmediato.
- **Alternativa descartada:** validar E.164 / email regex aquí. Es un motor de notificaciones, no un CMS; el provider (Fase 9) puede rechazar un recipient malo como error permanente. No inflar esta fase.
- **Capa:** `app/schemas/`. Puede importar enums de dominio. El dominio **no** importa este archivo.

- **Commit (si EsrgaN autoriza):**

```text
feat: validate notification send payloads with Pydantic v2

Reject unknown channels and empty recipients at the HTTP
boundary before a row is written.
```

---

### Paso 6.4 — Errores 404 / 503

Editar [`app/domain/exceptions.py`](app/domain/exceptions.py): añadir `NotificationNotFound`. No toques `InvalidStatusTransition`.

```python
"""Domain errors for business-rule failures.

HTTP mapping for status-machine errors is still a later phase.
NotificationNotFound is mapped in this phase because accept/status need a 404.
"""

from app.domain.enums import NotificationStatus


class DomainError(Exception):
    """Base for business-rule failures. HTTP mapping comes in a later phase."""


class InvalidStatusTransition(DomainError):
    def __init__(self, from_status: NotificationStatus, to_status: NotificationStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Cannot transition from {from_status} to {to_status}"
        )


class NotificationNotFound(DomainError):
    """No notification for this client (missing or not owned). Same HTTP 404 either way."""
```

Editar [`app/domain/__init__.py`](app/domain/__init__.py): exportar `NotificationNotFound` en `__all__`.

**No edites** [`app/api/errors.py`](app/api/errors.py): `QueueUnavailableError` ya está en `app/services/queue.py` (paso 6.1). El servicio no importa `app.api`.

Editar [`app/main.py`](app/main.py): registrar handlers **junto** a `UnauthorizedError` (puedes dejar el `include_router` de notifications para 6.6 si partes el commit; los handlers pueden existir antes). Cuerpos exactos:

- 404: `{"detail": "Notification not found", "code": "not_found"}`
- 503: `{"detail": "Queue unavailable", "code": "service_unavailable"}`

Imports nuevos: `NotificationNotFound` (dominio), `QueueUnavailableError` (desde `app.services.queue`). **No** añadas handler de `InvalidStatusTransition`.

- **Patrón:** excepciones de dominio vs errores del puerto. 404 = “este cliente no puede ver ese id”. 503 = “la cola no aceptó el id”.
- **Por qué no un mapper genérico ahora:** solo hay dos formas nuevas. Un `except DomainError` global tentaría a mapear transiciones ilegales que este path no usa.
- **Alternativa descartada:** `HTTPException` dentro del servicio. El servicio dejaría de ser testeable sin FastAPI y rompería la regla de capas.
- **Capa:** `NotificationNotFound` → `app/domain/`. `QueueUnavailableError` → `app/services/queue.py` (el puerto). Handlers → `create_app` (composition root). API puede importar services; **services no importan api**.

- **Commit (si EsrgaN autoriza):**

```text
feat: map missing notifications and queue failures to HTTP

Keep 404 identical for missing and foreign ids so clients
cannot probe another app's UUID space.
```

---

### Paso 6.5 — `NotificationService`

Crear [`app/services/notification_service.py`](app/services/notification_service.py). Responsabilidad única: caso de uso accept + lectura de status. Quién lo llama: el router vía `Depends`. **Aquí** está el `commit`.

```python
"""Use cases: accept a send request and read status for the owning client."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.exceptions import NotificationNotFound
from app.models.notification import Notification
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification import (
    NotificationStatusResponse,
    SendAcceptedResponse,
    SendNotificationRequest,
)
from app.services.queue import NotificationQueue, QueueUnavailableError

logger = logging.getLogger("app.notifications")


class NotificationService:
    def __init__(
        self,
        session: Session,
        repository: NotificationRepository,
        queue: NotificationQueue,
    ) -> None:
        self._session = session
        self._repository = repository
        self._queue = queue

    def accept(
        self,
        client_id: uuid.UUID,
        request: SendNotificationRequest,
    ) -> SendAcceptedResponse:
        """Persist PENDING, commit, enqueue id. Idempotent replays skip enqueue."""
        if request.idempotency_key is not None:
            existing = self._repository.get_by_idempotency_key(
                client_id, request.idempotency_key
            )
            if existing is not None:
                logger.info(
                    "notification_idempotent_replay",
                    extra={
                        "notification_id": str(existing.id),
                        "client_id": str(client_id),
                        "channel": existing.channel.value,
                        "status": existing.status.value,
                    },
                )
                return self._to_accepted(existing)

        row = self._repository.create(
            client_id=client_id,
            channel=request.channel,
            recipient=request.recipient,
            template=request.template,
            payload=request.payload,
            idempotency_key=request.idempotency_key,
        )
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if request.idempotency_key is None:
                raise
            winner = self._repository.get_by_idempotency_key(
                client_id, request.idempotency_key
            )
            if winner is None:
                raise
            return self._to_accepted(winner)

        try:
            self._queue.enqueue(row.id)
        except QueueUnavailableError:
            raise
        except Exception as exc:
            raise QueueUnavailableError() from exc

        logger.info(
            "notification_accepted",
            extra={
                "notification_id": str(row.id),
                "client_id": str(client_id),
                "channel": row.channel.value,
                "status": row.status.value,
            },
        )
        return self._to_accepted(row)

    def get_status(
        self,
        client_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> NotificationStatusResponse:
        """Return status for the owning client or raise NotificationNotFound."""
        row = self._repository.get_by_id_for_client(notification_id, client_id)
        if row is None:
            raise NotificationNotFound()
        logger.info(
            "notification_status_read",
            extra={
                "notification_id": str(row.id),
                "client_id": str(client_id),
                "channel": row.channel.value,
                "status": row.status.value,
            },
        )
        return NotificationStatusResponse(
            notification_id=row.id,
            status=row.status,
        )

    @staticmethod
    def _to_accepted(row: Notification) -> SendAcceptedResponse:
        return SendAcceptedResponse(notification_id=row.id, status=row.status)
```

El `except Exception` alrededor de `enqueue` es el **único** catch ancho permitido en esta fase, y **solo** para traducir fallos del adaptador a `QueueUnavailableError`. No lo uses en el resto del servicio. `QueueUnavailableError` se re-lanza tal cual (el handler HTTP).

Editar [`app/services/__init__.py`](app/services/__init__.py):

```python
"""Application services: use cases orchestrating domain and ports."""

from app.services.notification_service import NotificationService
from app.services.queue import (
    InMemoryNotificationQueue,
    NotificationQueue,
    QueueUnavailableError,
)

__all__ = [
    "InMemoryNotificationQueue",
    "NotificationQueue",
    "NotificationService",
    "QueueUnavailableError",
]
```

Crear [`tests/unit/services/test_notification_service.py`](tests/unit/services/test_notification_service.py). **Sin Postgres:** fakes en el propio archivo de test (no crees `app/utils/` ni un fake de producción).

```python
from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.enums import Channel, NotificationStatus
from app.domain.exceptions import NotificationNotFound
from app.models.notification import Notification
from app.schemas.notification import SendNotificationRequest
from app.services.notification_service import NotificationService
from app.services.queue import InMemoryNotificationQueue, QueueUnavailableError


class FakeSession:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self) -> None:
        if self.fail_commit:
            raise IntegrityError("INSERT", {}, Exception("unique"))
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


class FakeNotificationRepository:
    def __init__(self) -> None:
        self.rows: list[Notification] = []

    def create(
        self,
        *,
        client_id: uuid.UUID,
        channel: Channel,
        recipient: str,
        template: str,
        payload: dict[str, Any],
        idempotency_key: str | None,
    ) -> Notification:
        row = Notification(
            id=uuid.uuid4(),
            client_id=client_id,
            channel=channel,
            recipient=recipient,
            template=template,
            payload=payload,
            status=NotificationStatus.PENDING,
            idempotency_key=idempotency_key,
        )
        self.rows.append(row)
        return row

    def get_by_id_for_client(
        self,
        notification_id: uuid.UUID,
        client_id: uuid.UUID,
    ) -> Notification | None:
        for row in self.rows:
            if row.id == notification_id and row.client_id == client_id:
                return row
        return None

    def get_by_idempotency_key(
        self,
        client_id: uuid.UUID,
        idempotency_key: str,
    ) -> Notification | None:
        for row in self.rows:
            if row.client_id == client_id and row.idempotency_key == idempotency_key:
                return row
        return None


def _request(**overrides: object) -> SendNotificationRequest:
    data: dict[str, object] = {
        "channel": "email",
        "recipient": "user@example.com",
        "template": "welcome",
    }
    data.update(overrides)
    return SendNotificationRequest.model_validate(data)


def test_accept_persists_pending_commits_and_enqueues_once() -> None:
    session = FakeSession()
    repo = FakeNotificationRepository()
    queue = InMemoryNotificationQueue()
    service = NotificationService(session, repo, queue)
    client_id = uuid.uuid4()

    result = service.accept(client_id, _request())

    assert result.status is NotificationStatus.PENDING
    assert session.commit_calls == 1
    assert queue.enqueued == [result.notification_id]
    assert repo.rows[0].client_id == client_id


def test_accept_replay_returns_original_and_does_not_enqueue() -> None:
    session = FakeSession()
    repo = FakeNotificationRepository()
    queue = InMemoryNotificationQueue()
    service = NotificationService(session, repo, queue)
    client_id = uuid.uuid4()
    first = service.accept(
        client_id, _request(idempotency_key="checkout-99")
    )
    second = service.accept(
        client_id, _request(idempotency_key="checkout-99")
    )

    assert second.notification_id == first.notification_id
    assert queue.enqueued == [first.notification_id]
    assert session.commit_calls == 1


def test_accept_integrity_error_returns_winner_without_enqueue() -> None:
    client_id = uuid.uuid4()
    session = FakeSession(fail_commit=True)
    repo = FakeNotificationRepository()
    winner = repo.create(
        client_id=client_id,
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={},
        idempotency_key="race-1",
    )
    queue = InMemoryNotificationQueue()
    service = NotificationService(session, repo, queue)

    result = service.accept(client_id, _request(idempotency_key="race-1"))

    assert result.notification_id == winner.id
    assert session.rollback_calls == 1
    assert queue.enqueued == []


def test_accept_wraps_unexpected_queue_errors_as_unavailable() -> None:
    class BoomQueue:
        def enqueue(self, notification_id: uuid.UUID) -> None:
            raise RuntimeError("redis down")

    service = NotificationService(
        FakeSession(), FakeNotificationRepository(), BoomQueue()
    )
    with pytest.raises(QueueUnavailableError):
        service.accept(uuid.uuid4(), _request())


def test_get_status_raises_when_other_client() -> None:
    repo = FakeNotificationRepository()
    owner = uuid.uuid4()
    other = uuid.uuid4()
    row = repo.create(
        client_id=owner,
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={},
        idempotency_key=None,
    )
    service = NotificationService(FakeSession(), repo, InMemoryNotificationQueue())
    with pytest.raises(NotificationNotFound):
        service.get_status(other, row.id)
```

- **Patrón:** application service (caso de uso). Orquesta; no contiene SQL ni HTTP.
- **Por qué commit aquí:** ejemplo: si `get_db` commiteara al final del request, un fallo *después* del insert pero *antes* de encolar dejaría commits implícitos imposibles de razonar. `AGENTS.md` §6.4: el use case commitea a propósito.
- **Alternativa descartada:** encolar y luego commit. Un worker futuro podría tomar el UUID antes de que Postgres vea la fila (el cartero llega a una casa que aún no existe).
- **Capa:** `app/services/`. Puede importar dominio, repo, puerto, schemas. **No** importa routers.

- **Commit (si EsrgaN autoriza):**

```text
feat: accept notifications as PENDING then enqueue their id

Commit before enqueue so a 202 always has a durable row,
and replay the original id when the idempotency key matches.
```

---

### Paso 6.6 — Composition root + router HTTP

Editar [`app/api/deps.py`](app/api/deps.py): añadir `get_notification_queue` y `get_notification_service`. No construyas el queue ni el engine dentro del endpoint.

```python
def get_notification_queue(request: Request) -> NotificationQueue:
    """Return the queue adapter owned by lifespan (app.state)."""
    return request.app.state.notification_queue


def get_notification_service(
    session: Annotated[Session, Depends(get_db)],
    queue: Annotated[NotificationQueue, Depends(get_notification_queue)],
) -> NotificationService:
    """Compose the send/status use case for one request."""
    return NotificationService(
        session=session,
        repository=NotificationRepository(session),
        queue=queue,
    )
```

Añade los imports (`NotificationQueue`, `NotificationService`, `NotificationRepository`). `get_db` / `get_current_client` **no cambian** (cero `commit` en `get_db`).

Crear [`app/api/routers/notifications.py`](app/api/routers/notifications.py). Thin router: parse → Depends → service.

```python
"""Accept-send and status probe. Workers dispatch in a later phase."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_client, get_notification_service
from app.schemas.client import AuthenticatedClient
from app.schemas.notification import (
    NotificationStatusResponse,
    SendAcceptedResponse,
    SendNotificationRequest,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.post(
    "/send",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SendAcceptedResponse,
)
def send_notification(
    body: SendNotificationRequest,
    current_client: Annotated[AuthenticatedClient, Depends(get_current_client)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> SendAcceptedResponse:
    """Persist PENDING and enqueue. Does not call a provider."""
    return service.accept(current_client.id, body)


@router.get(
    "/{notification_id}/status",
    response_model=NotificationStatusResponse,
)
def read_notification_status(
    notification_id: uuid.UUID,
    current_client: Annotated[AuthenticatedClient, Depends(get_current_client)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationStatusResponse:
    """Return status for the owning client. 404 if missing or foreign."""
    return service.get_status(current_client.id, notification_id)
```

**Prohibido en el router:** `Session`, `select(Notification)`, `Notification` ORM, `queue.enqueue`.

Editar [`app/main.py`](app/main.py):

1. En `lifespan`, **después** de crear el engine:

```python
from app.services.queue import InMemoryNotificationQueue

application.state.notification_queue = InMemoryNotificationQueue()
```

2. Handlers 404/503 (si no quedaron en 6.4) + `include_router` del notifications router junto a clients.

Health sigue público. `/me` sigue igual.

- **Patrón:** composition root (`Depends` + `app.state`) + thin controller.
- **Por qué `app.state` para la cola:** ejemplo: tests reemplazan `client.app.state.notification_queue` por un `BoomQueue` y prueban 503 **sin** parchear el servicio.
- **Alternativa descartada:** singleton global `queue = InMemoryNotificationQueue()` a nivel de módulo. Los tests se pisan unos a otros; el lifespan ya es el dueño del engine.
- **Capa:** `app/api/`. Prefijo `/api/v1/` obligatorio. Health sigue sin versionar.

- **Commit (si EsrgaN autoriza):**

```text
feat: accept POST /send with 202 and expose notification status

Keep the HTTP path free of provider I/O so clients get a
stable notification_id under load.
```

---

### Paso 6.7 — Tests HTTP (Postgres real, filas commiteadas)

El `db_session` hace rollback. `TestClient` abre **otro** pool (lifespan). Igual que Fase 5: hay que **commitear** el cliente.

**Obligatorio:** [`tests/integration/conftest.py`](tests/integration/conftest.py) — el fixture `seeded_active_client` hoy borra solo `Client`. Tras esta fase hay filas hijas y el FK es `ON DELETE RESTRICT`. Antes de borrar el client:

```python
from sqlalchemy import delete

from app.models import Client, Notification

# en el teardown del fixture, DENTRO del `with factory() as session:`:
session.execute(delete(Notification).where(Notification.client_id == client_id))
session.execute(delete(Client).where(Client.id == client_id))
session.commit()
```

Crear [`tests/integration/test_send.py`](tests/integration/test_send.py) — **obligatorios**:

```python
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.domain.enums import NotificationStatus
from app.main import create_app
from app.models import Client, Notification
from app.services.queue import InMemoryNotificationQueue, QueueUnavailableError

_UNAUTHORIZED = {
    "detail": "Invalid or missing API key",
    "code": "unauthorized",
}
_NOT_FOUND = {
    "detail": "Notification not found",
    "code": "not_found",
}
_UNAVAILABLE = {
    "detail": "Queue unavailable",
    "code": "service_unavailable",
}

_MINIMAL_BODY = {
    "channel": "email",
    "recipient": "user@example.com",
    "template": "welcome",
}


def test_send_without_api_key_returns_401(client: TestClient) -> None:
    response = client.post("/api/v1/notifications/send", json=_MINIMAL_BODY)
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED


def test_send_invalid_channel_returns_422(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    response = client.post(
        "/api/v1/notifications/send",
        headers={"X-API-Key": raw},
        json={**_MINIMAL_BODY, "channel": "fax"},
    )
    assert response.status_code == 422


def test_send_returns_202_pending_and_enqueues_once(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    client_id, raw, _ = seeded_active_client
    response = client.post(
        "/api/v1/notifications/send",
        headers={"X-API-Key": raw},
        json=_MINIMAL_BODY,
    )
    assert response.status_code == 202
    body = response.json()
    notification_id = uuid.UUID(body["notification_id"])
    assert body["status"] == "PENDING"

    queue = client.app.state.notification_queue
    assert isinstance(queue, InMemoryNotificationQueue)
    assert queue.enqueued == [notification_id]

    factory = create_session_factory(persistence_engine)
    with factory() as session:
        row = session.get(Notification, notification_id)
        assert row is not None
        assert row.client_id == client_id
        assert row.status is NotificationStatus.PENDING


def test_send_replay_same_idempotency_key_does_not_double_enqueue(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    payload = {**_MINIMAL_BODY, "idempotency_key": "checkout-99"}
    headers = {"X-API-Key": raw}
    first = client.post("/api/v1/notifications/send", headers=headers, json=payload)
    second = client.post("/api/v1/notifications/send", headers=headers, json=payload)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["notification_id"] == second.json()["notification_id"]
    queue = client.app.state.notification_queue
    assert queue.enqueued == [uuid.UUID(first.json()["notification_id"])]


def test_status_own_notification_returns_pending(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    created = client.post(
        "/api/v1/notifications/send",
        headers={"X-API-Key": raw},
        json=_MINIMAL_BODY,
    )
    notification_id = created.json()["notification_id"]
    response = client.get(
        f"/api/v1/notifications/{notification_id}/status",
        headers={"X-API-Key": raw},
    )
    assert response.status_code == 200
    assert response.json() == {
        "notification_id": notification_id,
        "status": "PENDING",
    }


def test_status_foreign_or_missing_returns_same_404(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    _, raw, _ = seeded_active_client
    created = client.post(
        "/api/v1/notifications/send",
        headers={"X-API-Key": raw},
        json=_MINIMAL_BODY,
    )
    notification_id = created.json()["notification_id"]

    other_raw = generate_api_key()
    factory = create_session_factory(persistence_engine)
    with factory() as session:
        other = Client(
            name="other-app",
            hashed_api_key=hash_api_key(other_raw),
            is_active=True,
        )
        session.add(other)
        session.commit()
        other_id = other.id
    try:
        foreign = client.get(
            f"/api/v1/notifications/{notification_id}/status",
            headers={"X-API-Key": other_raw},
        )
        missing = client.get(
            f"/api/v1/notifications/{uuid.uuid4()}/status",
            headers={"X-API-Key": raw},
        )
        assert foreign.status_code == 404
        assert missing.status_code == 404
        assert foreign.json() == _NOT_FOUND
        assert missing.json() == _NOT_FOUND
    finally:
        with factory() as session:
            session.execute(delete(Notification).where(Notification.client_id == other_id))
            session.delete(session.get(Client, other_id))
            session.commit()


def test_send_returns_503_when_queue_raises(
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    client_id, raw, _ = seeded_active_client

    class BoomQueue:
        def enqueue(self, notification_id: uuid.UUID) -> None:
            raise QueueUnavailableError()

    with TestClient(create_app()) as test_client:
        test_client.app.state.notification_queue = BoomQueue()
        response = test_client.post(
            "/api/v1/notifications/send",
            headers={"X-API-Key": raw},
            json=_MINIMAL_BODY,
        )
        assert response.status_code == 503
        assert response.json() == _UNAVAILABLE
        factory = create_session_factory(persistence_engine)
        with factory() as session:
            rows = session.scalars(
                select(Notification).where(Notification.client_id == client_id)
            ).all()
            assert len(rows) == 1
            assert rows[0].status is NotificationStatus.PENDING
```

El 503 **no** incluye `notification_id` en el JSON: la fila se afirma con `select` por `client_id`. El test foreign/missing usa `delete(Notification)` (SQLAlchemy 2), igual que el conftest.

`test_health_still_ok_without_api_key` ya existe en auth; no lo dupliques salvo que quieras un assert corto aquí. `/send` no debe aparecer en tests de health.

**Prohibido:** `time.sleep`, Twilio, `create_all`, `task_always_eager`, pegarle a Redis, mockear `NotificationService` entero en el test HTTP (queremos la fila real).

- **Patrón:** test de integración HTTP + BD real + puerto reemplazable.
- **Por qué commit y no rollback:** las dos cajas (pool del test vs pool de la app) no comparten la transacción. Igual que `/me`.
- **Alternativa descartada:** Celery eager. Aún no hay Celery; el puerto in-memory **es** el doble.
- **Capa:** `tests/integration/`.

- **Commit (si EsrgaN autoriza):**

```text
test: accept send with 202 and hide foreign notification ids

Prove persist-then-enqueue against local Postgres, including
idempotent replay and 404 isolation between clients.
```

---

### Paso 6.8 — Docs de status + README

Editar [`docs/STATUS.md`](docs/STATUS.md) **solo al cerrar la implementación** (otro turno, o el final de este PLAN cuando el código exista):

- Marcar Fase 6 hecha: `POST /send` 202, `GET …/status`, `NotificationService`, puerto in-memory, idempotencia.
- Decir qué **sigue**: Fase 7 = métricas (conteos por cliente). Todavía no Redis/Celery.
- “Qué no existe” sigue incluyendo Redis, Token Bucket, Celery, providers, DLQ, Docker, mapper de `InvalidStatusTransition`.
- No marcar Fase 7 como hecha.

Editar [`README.md`](README.md):

- Status: “Phase 6: `POST /api/v1/notifications/send` returns 202 and persists PENDING; in-memory queue port; still no Celery/Redis”.
- Curl (después del seed de cliente de Fase 5):

```bash
curl -i -H "X-API-Key: PASTE_RAW_KEY" -H "Content-Type: application/json" \
  -d '{"channel":"email","recipient":"user@example.com","template":"welcome","payload":{"name":"Ada"},"idempotency_key":"welcome-1"}' \
  http://127.0.0.1:8000/api/v1/notifications/send
# 202 {"notification_id":"...","status":"PENDING"}

curl -i -H "X-API-Key: PASTE_RAW_KEY" \
  http://127.0.0.1:8000/api/v1/notifications/NOTIFICATION_ID/status
# 200 {"notification_id":"...","status":"PENDING"}
```

- Dejar claro: **no sale ningún email**. La cola in-memory no despacha.
- Docker sigue “fase posterior”.

- **Commit (si EsrgaN autoriza):**

```text
docs: record accept-send 202 and status probe in the runbook
```

---

## 4. Checklist de cierre

- [ ] `pytest -q` verde (44 anteriores + queue + schemas + service fakes + repo + send HTTP)
- [ ] `ruff check app tests` limpio
- [ ] `app/domain/` sigue sin importar FastAPI/SQLAlchemy/Pydantic
- [ ] Router de notifications no importa `app.models` ni `Session`
- [ ] Cero `create_all`, cero migración nueva, cero `commit` en `get_db`
- [ ] `POST /send` → 202 + fila `PENDING` + `enqueue` una vez
- [ ] Replay con misma `idempotency_key` → mismo id, sin segundo enqueue
- [ ] `GET …/status` 200 propio / 404 ajeno o missing (mismo cuerpo)
- [ ] `GET /health` sigue 200 sin `X-API-Key`
- [ ] Cero Celery, cero Redis, cero JWT, cero Docker, cero `BackgroundTasks`, cero `/metrics`
- [ ] 3–6 learning points en español **simple** para EsrgaN (qué es 202 vs 200, qué es un puerto vs Celery, por qué commit-then-enqueue, qué es idempotencia, por qué 404 no dice “no es tuyo”, por qué la cola in-memory no envía)
- [ ] Commits hechos o mensajes esperando a EsrgaN

**Prohibido al terminar:** worker Celery, `import twilio`, Token Bucket, Compose, métricas, mapper de transiciones.

---

## 5. Qué sigue (no implementar)

Siguiente `PLAN.md` (otra reescritura): **Metrics** — conteos de envíos OK vs fallo **por cliente autenticado**. Todavía no hay Redis ni Celery: los conteos salen de Postgres (`SENT`/`FAILED`). Hoy casi todo será `PENDING`; el endpoint y la query igual se construyen. No implementar eso en este turno.
