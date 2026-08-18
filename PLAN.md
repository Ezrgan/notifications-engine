# PLAN.md — Fase 7: Metrics (conteos `sent` / `failed` por cliente)

> **REGLA OBLIGATORIA PARA TODOS LOS AGENTES:**
> Antes de ejecutar cualquier paso, leer y acatar [`AGENTS.md`](./AGENTS.md), [`.cursor/rules/`](./.cursor/rules/) (sobre todo `fastapi.mdc`, `postgresql.mdc` y `testing.mdc`) y [`docs/HOW_TO_WRITE_THE_NEXT_PLAN.md`](./docs/HOW_TO_WRITE_THE_NEXT_PLAN.md).
> Este archivo es el **único plan ejecutable**. Describe **una sola fase**. Cuando cierre, EsrgaN **reescribe** `PLAN.md` entero (ver el playbook en `docs/`).
> No implementar Redis, Token Bucket, 429, Celery, providers, DLQ, Prometheus/Grafana, JWT, alta HTTP de clientes ni Docker.

> **Cómo está pensado este documento:**
> Un agente debe poder implementarlo **sin inventar**. Cada paso: archivos exactos, contrato, tests, commit propuesto, qué no tocar.
> Código completo. Cero placeholders. Cero `# ... rest of code ...`.
> Enseñar a EsrgaN en **español simple**, con ejemplos. Sin jerga sin definir.

> **Estado de partida (verificado):**
> Rama actual `main` = `7a2b828` (`docs: stop freezing the next-phase number in the playbook`).
> `origin/main` = el mismo commit. Fase 6 ya está fusionada (`9923ddb` = PR **#7**).
> `pytest -q` → **66 passed**. `ruff check app tests` limpio.
> Hay `POST /api/v1/notifications/send` → 202 + `PENDING`, `GET …/status`, `NotificationService`, `NotificationRepository`, cola in-memory, `X-API-Key`.
> **No** existe `GET /metrics`, `MetricsService`, query `COUNT`, Redis, Celery, ni worker que ponga filas en `SENT`/`FAILED`. `REDIS_URL` sigue comentado en `.env.example`. `pyproject.toml` no lista `celery` ni `redis`.

---

## 0. Decisiones congeladas (esta fase)

| # | Decisión | Valor congelado |
| --- | --- | --- |
| D1 | Idea de la fase | El cliente autenticado lee **cuántos envíos suyos ya terminaron bien vs mal**. `GET /api/v1/metrics` → **200** `{"sent": N, "failed": M}`. Nadie envía un email. Nadie arranca Prometheus. |
| D2 | Qué cuentan `sent` y `failed` | `sent` = filas con `status = SENT`. `failed` = filas con `status = FAILED`. Ejemplo: el checkout hace 10 `POST /send`; las 10 están `PENDING`; metrics devuelve `{"sent":0,"failed":0}`. Eso **es correcto**: aceptar trabajo no es haberlo entregado. |
| D3 | Qué **no** cuentan | `PENDING` y `PROCESSING` **no** entran en ningún campo. No añadas `pending`, `processing`, `total`, `queued` ni desglose por canal. El contrato de `AGENTS.md` §5.1 es “success vs failure”, no un dashboard. |
| D4 | Fuente de verdad | **Postgres**, query `COUNT` filtrada por `client_id`. No hay tabla nueva. No hay contador en Redis (Redis no existe; además se desfasaría de las filas). No hay proceso que incremente un entero en RAM. |
| D5 | Query (una ida a la BD) | Un `SELECT` con `count(*) FILTER (WHERE status = 'SENT')` y el mismo para `FAILED`, `WHERE client_id = :id`. **Sin** `GROUP BY` (un cliente sin filas seguiría devolviendo una fila `(0, 0)`; un `GROUP BY` vacío no). **Prohibido** `select(Notification)` y sumar en Python. |
| D6 | Vacío | Cero filas del cliente → **200** `{"sent":0,"failed":0}`. **Nunca** 404. 404 significaría “no existe el recurso metrics”; el recurso existe, los conteos son cero. |
| D7 | Aislamiento | El `WHERE client_id` **es** la autorización. Las `SENT` de la app B no aparecen en el GET de la app A. No hay endpoint admin. No hay métricas globales. |
| D8 | HTTP | `GET /api/v1/metrics` + `X-API-Key`. **200** con el schema de D1. Auth rota → **401** idéntico a `/me` y `/send` (`{"detail":"Invalid or missing API key","code":"unauthorized"}` + `WWW-Authenticate: ApiKey`). Sin body. Sin query params. |
| D9 | Capas | Router → schemas + `Depends` + `MetricsService`. Servicio → repositorio (solo lectura). Repositorio → SQLAlchemy `COUNT`. Router **no** importa `app.models` ni `Session`. `NotificationService` **no** gana un método `get_metrics` (ver D10). |
| D10 | Servicio propio, no inflar el de send | `MetricsService` en `app/services/metrics_service.py`. Responsabilidad: caso de uso “leer conteos del cliente”. **No** recibe cola. **No** hace `commit`. `NotificationService` ya exige `queue` para accept; colgar metrics ahí obligaría a inyectar un puerto que este GET no usa. |
| D11 | DTO del repositorio vs HTTP | El repo devuelve `ClientSendCounts` (`dataclass(frozen=True)` con `sent: int`, `failed: int`) **en el mismo archivo del repo**. El schema HTTP `ClientMetricsResponse` vive en `app/schemas/metrics.py`. El repositorio **no** importa Pydantic. El router **no** ve el dataclass. |
| D12 | Cómo aparecen `SENT`/`FAILED` en tests | **Insertar filas** con ese `status` (sesión de test). No hay worker. **No** llames a la máquina de estados para “simular un envío”. **No** hagas `POST /send` y luego `UPDATE` en el test HTTP del camino feliz de metrics: el test de “POST no mueve metrics” es otro (D17). |
| D13 | Settings / Alembic / libs | **Cero** campo nuevo (`REDIS_URL` sigue comentado). **Cero** revisión Alembic (`client_id` ya está indexado). **Cero** `prometheus-client`, `redis`, `celery`. Cero `CREATE INDEX` nuevo. |
| D14 | Logs | Un `metrics_read` con `client_id`, `sent`, `failed`. **Nunca** API key, payload ni recipient. |
| D15 | `get_db` | Sigue **sin** `commit`. Este caso de uso no escribe. |
| D16 | Fuera de esta fase | Redis, Token Bucket, 429, Celery, provider simulado, retries/DLQ, mapper de `InvalidStatusTransition`, `ClientService`, JWT, Docker, Grafana, `/metrics` estilo Prometheus (texto `sent_total 3`). |
| D17 | Tests | Unitarios: servicio con **fake** de repo (sin Postgres). Integración repo: `COUNT` con `db_session` (rollback). Integración HTTP: filas **commiteadas** + `TestClient` (otro pool, igual que `/send`). Obligatorio: 401; ceros; POST `/send` no incrementa `sent`; aislamiento entre clientes; `PENDING`/`PROCESSING` no cuentan. Cero `time.sleep`. Cero SQLite. Cero Twilio. |
| D18 | Git | Rama `feat/phase-7-metrics` **desde** `main` (`7a2b828`). Fase 6 ya está en `main`; no partir de `feat/phase-6-accept-send`. Commits **solo si EsrgaN lo pide**. |
| D19 | Docker / extras | Prohibidos. No Kafka, JWT, Prisma, Redis, Celery, Compose, Prometheus. |

---

## 1. Diagnóstico (por qué esta fase)

Archivos reales, no memoria:

1. [`docs/STATUS.md`](docs/STATUS.md) marca Fases 1–6 hechas. [`AGENTS.md`](AGENTS.md) §10.1 siguiente número libre = **7 Metrics**. No saltar a Redis (8) ni Celery (9): un Token Bucket no enseña el contrato de “éxito vs fallo”, y sin worker igual necesitamos poder **leer** el agregado.
2. [`app/api/routers/notifications.py`](app/api/routers/notifications.py) solo tiene `POST /send` y `GET /{id}/status`. [`app/main.py`](app/main.py) monta health + clients + notifications. **No** hay ruta `/metrics`.
3. [`app/repositories/notification_repository.py`](app/repositories/notification_repository.py) sabe `create`, `get_by_id_for_client`, `get_by_idempotency_key`. **No** hay `COUNT`. [`app/services/notification_service.py`](app/services/notification_service.py) orquesta accept + status y **exige** `NotificationQueue`.
4. [`app/models/notification.py`](app/models/notification.py) ya tiene `status` (`PENDING`/`PROCESSING`/`SENT`/`FAILED`) e índice en `client_id`. No hace falta migración: contar no cambia el esquema.
5. Ejemplo de uso: `curl -H 'X-API-Key: ne_…' GET /api/v1/metrics` → `200 {"sent":0,"failed":0}` el día 1 (todo es `PENDING`). El día que el worker (Fase 9) marque 3 `SENT` y 1 `FAILED`, el mismo curl devuelve `{"sent":3,"failed":1}` **sin cambiar este endpoint**.

---

## 2. Árbol al cerrar esta fase

```text
app/repositories/notification_repository.py   # EDITAR: ClientSendCounts + count_sent_and_failed_for_client
app/repositories/__init__.py                  # no hace falta reexportar el dataclass
app/schemas/metrics.py                        # NUEVO: ClientMetricsResponse
app/services/metrics_service.py               # NUEVO: get_client_metrics
app/services/__init__.py                      # EDITAR: reexportar MetricsService
app/api/deps.py                               # EDITAR: get_metrics_service
app/api/routers/metrics.py                    # NUEVO: GET /api/v1/metrics
app/main.py                                   # EDITAR: include_router metrics
tests/unit/services/test_metrics_service.py   # NUEVO (fake repo, sin Postgres)
tests/integration/test_notification_repository.py  # EDITAR: tests del COUNT
tests/integration/test_metrics.py             # NUEVO (filas commiteadas + TestClient)
README.md                                     # EDITAR: curl metrics
docs/STATUS.md                                # EDITAR en el último paso de implementación
```

**No crear:** `celery_app.py`, `tasks.py`, `app/providers/*` reales, `Dockerfile`, `docker-compose.yml`, revisión Alembic, cliente Redis, middleware Token Bucket, `BackgroundTasks`, tabla `metrics`, `prometheus-client`.

**No tocar:** máquina de estados, modelos/columnas, `GET /health`, `SECRET_KEY` / `DATABASE_URL`, `hash_api_key`, `create_all`, `pyproject.toml` dependencies, `NotificationService.accept` / `get_status`, puerto de cola, `app/api/errors.py`.

---

## 3. Git

Fase 6 ya está en `main` (`7a2b828`). Crear la rama así:

```bash
git checkout main
# HEAD esperado: 7a2b828
git pull   # si EsrgaN lo pide; origin/main ya estaba en 7a2b828 al escribir este PLAN
git checkout -b feat/phase-7-metrics
```

**Nunca** partir de `feat/phase-6-accept-send` ni commitear en `main`.

Antes de cerrar cada paso de código:

```bash
source .venv/bin/activate
pytest -q
ruff check app tests
```

Los 66 tests de Fases 2–6 deben seguir verdes (más los nuevos de esta fase).

---

## FASE 0 — Preparación

- [ ] `pytest -q` → 66 passed **antes** de editar
- [ ] `ruff check app tests` limpio
- [ ] Postgres local sigue arriba (`psql -d notifications_engine_test -c 'SELECT 1'`)
- [ ] Rama `feat/phase-7-metrics` creada desde `main` (`7a2b828`)
- [ ] Cero Docker, cero `uv pip install redis` / `celery` / `prometheus-client`
- [ ] Enseñar a EsrgaN (ejemplo): **métricas de producto** ≠ **métricas de servidor**. `GET /metrics` aquí es “de mis 100 SMS, 97 llegaron y 3 fallaron”. Prometheus sería “este proceso FastAPI va a 50 req/s”; eso no es el contrato de v1. Contar en Postgres es como preguntarle al archivo de la oficina cuántos paquetes salieron; un número en un papelito al lado de la puerta se pierde si cambia el turno.

---

## FASE 7 — Metrics

### Paso 7.1 — `COUNT` en el repositorio

Editar [`app/repositories/notification_repository.py`](app/repositories/notification_repository.py). Responsabilidad nueva: un agregado de lectura por cliente. Quién lo llama: `MetricsService`. El router **no** lo llama.

Dejar `create` / `get_by_id_for_client` / `get_by_idempotency_key` **iguales**. Añadir el dataclass y el método. El archivo queda así (completo):

```python
"""Data access for Notification rows. Routers must not query Session themselves."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import Channel, NotificationStatus
from app.models.notification import Notification


@dataclass(frozen=True)
class ClientSendCounts:
    """Terminal send counts for one client. PENDING/PROCESSING are not included."""

    sent: int
    failed: int


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

    def count_sent_and_failed_for_client(self, client_id: uuid.UUID) -> ClientSendCounts:
        """Return SENT/FAILED counts for ``client_id`` without loading rows."""
        stmt = select(
            func.count().filter(Notification.status == NotificationStatus.SENT),
            func.count().filter(Notification.status == NotificationStatus.FAILED),
        ).where(Notification.client_id == client_id)
        sent, failed = self._session.execute(stmt).one()
        return ClientSendCounts(sent=int(sent or 0), failed=int(failed or 0))
```

**Prohibido:** un `get_all_for_client` que traiga la tabla a RAM. Un `count_by_status` genérico que invite a exponer `PENDING` en HTTP.

Editar [`tests/integration/test_notification_repository.py`](tests/integration/test_notification_repository.py): **añadir** al final (no borres los tests de `create` / lookup). Imports nuevos: `Notification` desde `app.models`.

```python
from app.models import Client, Notification
```

Helper y tests nuevos (el `_client` que ya existe se reutiliza):

```python
def _row(
    session: Session,
    client_id: uuid.UUID,
    status: NotificationStatus,
) -> Notification:
    row = Notification(
        client_id=client_id,
        channel=Channel.EMAIL,
        recipient="user@example.com",
        template="welcome",
        payload={},
        status=status,
    )
    session.add(row)
    return row


def test_count_sent_and_failed_ignores_pending_and_processing(db_session: Session) -> None:
    client = _client(db_session)
    repo = NotificationRepository(db_session)
    _row(db_session, client.id, NotificationStatus.PENDING)
    _row(db_session, client.id, NotificationStatus.PENDING)
    _row(db_session, client.id, NotificationStatus.PROCESSING)
    _row(db_session, client.id, NotificationStatus.SENT)
    _row(db_session, client.id, NotificationStatus.SENT)
    _row(db_session, client.id, NotificationStatus.SENT)
    _row(db_session, client.id, NotificationStatus.FAILED)
    db_session.flush()

    counts = repo.count_sent_and_failed_for_client(client.id)
    assert counts.sent == 3
    assert counts.failed == 1


def test_count_sent_and_failed_is_zero_when_client_has_no_rows(db_session: Session) -> None:
    client = _client(db_session)
    repo = NotificationRepository(db_session)
    counts = repo.count_sent_and_failed_for_client(client.id)
    assert counts.sent == 0
    assert counts.failed == 0


def test_count_sent_and_failed_hides_other_clients_rows(db_session: Session) -> None:
    owner = _client(db_session)
    other = _client(db_session)
    repo = NotificationRepository(db_session)
    _row(db_session, owner.id, NotificationStatus.SENT)
    _row(db_session, other.id, NotificationStatus.SENT)
    _row(db_session, other.id, NotificationStatus.FAILED)
    db_session.flush()

    counts = repo.count_sent_and_failed_for_client(owner.id)
    assert counts.sent == 1
    assert counts.failed == 0
```

- **Patrón:** repository (agregado de lectura). La query con `client_id` **es** la regla de autorización, igual que `get_by_id_for_client`.
- **Por qué `FILTER` y no `GROUP BY`:** ejemplo: un cliente nuevo no tiene filas. `COUNT(*) FILTER (...)` igual devuelve una fila `(0, 0)`. Un `GROUP BY status` sobre cero filas no devuelve filas; tendrías que “inventar” los ceros en Python.
- **Alternativa descartada:** `session.scalars(select(Notification).where(...)).all()` y `sum(...)`. Con miles de notificaciones/día sigue “funcionando”, pero enseña el anti-patrón de traer el archivo entero para contar las páginas. `COUNT` es trabajo de Postgres.
- **Capa:** `app/repositories/`. Puede importar modelos y dominio. **No** puede importar FastAPI ni `app.schemas`.

- **Commit (si EsrgaN autoriza):**

```text
feat: count sent and failed notifications per client

Keep the aggregate in Postgres so metrics never load another
app's rows or treat PENDING as a successful send.
```

---

### Paso 7.2 — Schema + `MetricsService`

Crear [`app/schemas/metrics.py`](app/schemas/metrics.py). Responsabilidad: contrato HTTP de metrics. Quién lo usa: router y servicio (el servicio **devuelve** este schema, no el dataclass del repo).

```python
"""Pydantic v2 schema for client-scoped send metrics."""

from pydantic import BaseModel, Field


class ClientMetricsResponse(BaseModel):
    sent: int = Field(ge=0)
    failed: int = Field(ge=0)
```

No hace falta `extra="forbid"`: este modelo **sale** del servidor, no entra de un body. No hace falta test unitario de schema (no hay request que rechazar); el test HTTP cubre la serialización.

Crear [`app/services/metrics_service.py`](app/services/metrics_service.py). Responsabilidad única: caso de uso “leer conteos”. Quién lo llama: el router vía `Depends`. **No** hay `commit`. **No** hay cola.

```python
"""Use case: read SENT/FAILED counts for the authenticated client."""

from __future__ import annotations

import logging
import uuid

from app.repositories.notification_repository import NotificationRepository
from app.schemas.metrics import ClientMetricsResponse

logger = logging.getLogger("app.metrics")


class MetricsService:
    def __init__(self, repository: NotificationRepository) -> None:
        self._repository = repository

    def get_client_metrics(self, client_id: uuid.UUID) -> ClientMetricsResponse:
        """Return terminal send counts. Empty history is zeros, not an error."""
        counts = self._repository.count_sent_and_failed_for_client(client_id)
        logger.info(
            "metrics_read",
            extra={
                "client_id": str(client_id),
                "sent": counts.sent,
                "failed": counts.failed,
            },
        )
        return ClientMetricsResponse(sent=counts.sent, failed=counts.failed)
```

Editar [`app/services/__init__.py`](app/services/__init__.py):

```python
"""Application services: use cases orchestrating domain and ports."""

from app.services.metrics_service import MetricsService
from app.services.notification_service import NotificationService
from app.services.queue import (
    InMemoryNotificationQueue,
    NotificationQueue,
    QueueUnavailableError,
)

__all__ = [
    "InMemoryNotificationQueue",
    "MetricsService",
    "NotificationQueue",
    "NotificationService",
    "QueueUnavailableError",
]
```

Crear [`tests/unit/services/test_metrics_service.py`](tests/unit/services/test_metrics_service.py). **Sin Postgres:** fake en el propio archivo de test.

```python
from __future__ import annotations

import uuid

from app.repositories.notification_repository import ClientSendCounts
from app.services.metrics_service import MetricsService


class FakeNotificationRepository:
    def __init__(self) -> None:
        self.counts_by_client: dict[uuid.UUID, ClientSendCounts] = {}

    def count_sent_and_failed_for_client(self, client_id: uuid.UUID) -> ClientSendCounts:
        return self.counts_by_client.get(client_id, ClientSendCounts(sent=0, failed=0))


def test_get_client_metrics_returns_repo_counts() -> None:
    repo = FakeNotificationRepository()
    client_id = uuid.uuid4()
    repo.counts_by_client[client_id] = ClientSendCounts(sent=4, failed=2)
    service = MetricsService(repo)

    result = service.get_client_metrics(client_id)

    assert result.sent == 4
    assert result.failed == 2


def test_get_client_metrics_returns_zeros_when_repo_has_no_row() -> None:
    service = MetricsService(FakeNotificationRepository())
    result = service.get_client_metrics(uuid.uuid4())
    assert result.sent == 0
    assert result.failed == 0


def test_get_client_metrics_does_not_see_another_client() -> None:
    repo = FakeNotificationRepository()
    owner = uuid.uuid4()
    other = uuid.uuid4()
    repo.counts_by_client[owner] = ClientSendCounts(sent=1, failed=0)
    repo.counts_by_client[other] = ClientSendCounts(sent=9, failed=9)
    service = MetricsService(repo)

    result = service.get_client_metrics(owner)

    assert result.sent == 1
    assert result.failed == 0
```

- **Patrón:** application service (caso de uso de lectura). Orquesta; no contiene SQL ni HTTP.
- **Por qué un servicio y no el router → repo:** ejemplo: mañana quieres cachear 5 segundos o denegar a un cliente inactivo con un error de dominio. El router seguiría siendo 4 líneas. Hoy el servicio es delgado a propósito; eso no es un motivo para saltárselo.
- **Alternativa descartada:** método `get_metrics` en `NotificationService`. Ese servicio ya pide `queue` en el constructor. Un test unitario de metrics tendría que fabricar una cola falsa que nunca se llama. Dos constructores distintos = dos casos de uso.
- **Capa:** `app/services/`. Puede importar repo + schemas. **No** importa routers. **No** importa `app.models` (el dataclass del repo basta).

- **Commit (si EsrgaN autoriza):**

```text
feat: add MetricsService for client-scoped send counts

Keep the read model off NotificationService so metrics does
not depend on the queue port.
```

---

### Paso 7.3 — Composition root + router HTTP + tests

Editar [`app/api/deps.py`](app/api/deps.py): añadir `get_metrics_service`. No construyas el engine dentro del endpoint. `get_notification_service` **no cambia**.

Imports nuevos: `MetricsService`.

```python
def get_metrics_service(
    session: Annotated[Session, Depends(get_db)],
) -> MetricsService:
    """Compose the metrics read use case for one request."""
    return MetricsService(repository=NotificationRepository(session))
```

Crear [`app/api/routers/metrics.py`](app/api/routers/metrics.py). Thin router: Depends → service. Prefijo `/api/v1` (el path del producto es `/api/v1/metrics`, **no** `/api/v1/notifications/metrics`).

```python
"""Client-scoped SENT/FAILED counts. Does not dispatch or rate-limit."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_client, get_metrics_service
from app.schemas.client import AuthenticatedClient
from app.schemas.metrics import ClientMetricsResponse
from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/api/v1", tags=["metrics"])


@router.get("/metrics", response_model=ClientMetricsResponse)
def read_metrics(
    current_client: Annotated[AuthenticatedClient, Depends(get_current_client)],
    service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> ClientMetricsResponse:
    """Return SENT/FAILED counts for the authenticated client."""
    return service.get_client_metrics(current_client.id)
```

**Prohibido en el router:** `Session`, `select(Notification)`, `func.count`, `Notification` ORM.

Editar [`app/main.py`](app/main.py):

```python
from app.api.routers.metrics import router as metrics_router
```

Junto a los otros `include_router`:

```python
application.include_router(health_router)
application.include_router(clients_router)
application.include_router(notifications_router)
application.include_router(metrics_router)
```

Health sigue público. `/send` y `/me` siguen igual. **No** añadas handlers nuevos (401 ya existe; este GET no lanza 404/503).

Crear [`tests/integration/test_metrics.py`](tests/integration/test_metrics.py) — **obligatorios**:

```python
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.domain.enums import Channel, NotificationStatus
from app.models import Client, Notification

_UNAUTHORIZED = {
    "detail": "Invalid or missing API key",
    "code": "unauthorized",
}

_MINIMAL_BODY = {
    "channel": "email",
    "recipient": "user@example.com",
    "template": "welcome",
}


def _commit_notification(
    engine: Engine,
    client_id: uuid.UUID,
    status: NotificationStatus,
) -> None:
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(
            Notification(
                client_id=client_id,
                channel=Channel.EMAIL,
                recipient="user@example.com",
                template="welcome",
                payload={},
                status=status,
            )
        )
        session.commit()


def test_metrics_without_api_key_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/metrics")
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED


def test_metrics_empty_history_returns_zeros(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    response = client.get("/api/v1/metrics", headers={"X-API-Key": raw})
    assert response.status_code == 200
    assert response.json() == {"sent": 0, "failed": 0}


def test_metrics_ignores_pending_from_post_send(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    accepted = client.post(
        "/api/v1/notifications/send",
        headers={"X-API-Key": raw},
        json=_MINIMAL_BODY,
    )
    assert accepted.status_code == 202
    response = client.get("/api/v1/metrics", headers={"X-API-Key": raw})
    assert response.status_code == 200
    assert response.json() == {"sent": 0, "failed": 0}


def test_metrics_counts_only_own_sent_and_failed(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    owner_id, raw, _ = seeded_active_client
    _commit_notification(persistence_engine, owner_id, NotificationStatus.SENT)
    _commit_notification(persistence_engine, owner_id, NotificationStatus.SENT)
    _commit_notification(persistence_engine, owner_id, NotificationStatus.FAILED)
    _commit_notification(persistence_engine, owner_id, NotificationStatus.PENDING)
    _commit_notification(persistence_engine, owner_id, NotificationStatus.PROCESSING)

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
        _commit_notification(persistence_engine, other_id, NotificationStatus.SENT)
        _commit_notification(persistence_engine, other_id, NotificationStatus.FAILED)

        mine = client.get("/api/v1/metrics", headers={"X-API-Key": raw})
        theirs = client.get("/api/v1/metrics", headers={"X-API-Key": other_raw})
        assert mine.status_code == 200
        assert mine.json() == {"sent": 2, "failed": 1}
        assert theirs.status_code == 200
        assert theirs.json() == {"sent": 1, "failed": 1}
    finally:
        with factory() as session:
            session.execute(delete(Notification).where(Notification.client_id == other_id))
            session.delete(session.get(Client, other_id))
            session.commit()
```

`seeded_active_client` ya borra las `Notification` del owner en el teardown ([`tests/integration/conftest.py`](tests/integration/conftest.py)). El `finally` solo limpia al **otro** cliente. No edites el conftest salvo que un test nuevo deje basura (no debería).

**Prohibido:** `time.sleep`, Twilio, `create_all`, pegarle a Redis, mockear `MetricsService` entero en el test HTTP (queremos el `COUNT` real). No añadas un test de 429: no hay limiter.

- **Patrón:** composition root (`Depends`) + thin controller + test de integración HTTP + BD real.
- **Por qué insertar `SENT` a mano:** ejemplo: el cartero (worker) aún no existe. El test dice “si **ya hubiera** dos entregas y un fallo, el mostrador mostraría 2 y 1”. No fingimos el envío; sembramos el estado terminal.
- **Alternativa descartada:** endpoint Prometheus `text/plain` con `sent_total`. Eso lo scrapearía Grafana, no la app checkout. El cliente máquina necesita JSON igual que `/status`.
- **Capa:** `app/api/` + `tests/integration/`. Prefijo `/api/v1/` obligatorio. Health sigue sin versionar.

- **Commit (si EsrgaN autoriza):**

```text
feat: expose GET /metrics for authenticated client send counts

Scope COUNT to the API key so one app cannot read another
app's success and failure totals.
```

---

### Paso 7.4 — Docs de status + README

Editar [`docs/STATUS.md`](docs/STATUS.md) **solo al cerrar la implementación** (otro turno, o el final de este PLAN cuando el código exista):

- Marcar Fase 7 hecha: `GET /api/v1/metrics` 200 `{sent, failed}`, `MetricsService`, `COUNT` por `client_id`, ceros si solo hay `PENDING`.
- Decir qué **sigue**: Fase 8 = Token Bucket en Redis Homebrew + HTTP 429. Todavía no hay Celery.
- “Qué no existe” **deja de listar** `GET /metrics`. Sigue incluyendo Redis, Token Bucket, Celery, providers, DLQ, Docker, mapper de `InvalidStatusTransition`.
- No marcar Fase 8 como hecha.

Editar [`README.md`](README.md):

- Status: “Phase 7: `GET /api/v1/metrics` returns `{sent, failed}` per API key from Postgres; still no Redis/Celery”.
- Curl (después del de status):

```bash
curl -i -H "X-API-Key: PASTE_RAW_KEY" http://127.0.0.1:8000/api/v1/metrics
# 200 {"sent":0,"failed":0}
# zeros until a later worker marks rows SENT or FAILED
```

- Dejar claro: **POST /send no mueve estos números**. Docker sigue “fase posterior”.

- **Commit (si EsrgaN autoriza):**

```text
docs: record GET /metrics in the local runbook
```

---

## 4. Checklist de cierre

- [ ] `pytest -q` verde (66 anteriores + COUNT repo + MetricsService fake + metrics HTTP)
- [ ] `ruff check app tests` limpio
- [ ] `app/domain/` sigue sin importar FastAPI/SQLAlchemy/Pydantic
- [ ] Router de metrics no importa `app.models` ni `Session`
- [ ] `MetricsService` no importa cola ni hace `commit`
- [ ] Cero `create_all`, cero migración nueva, cero `commit` en `get_db`
- [ ] `GET /api/v1/metrics` → 200 `{sent, failed}` con `X-API-Key`
- [ ] Sin key → 401 idéntico a `/me`
- [ ] Historial vacío o solo `PENDING` → `{"sent":0,"failed":0}` (no 404)
- [ ] Filas de otro cliente no aparecen en los conteos
- [ ] `GET /health` sigue 200 sin `X-API-Key`
- [ ] Cero Redis, cero Celery, cero JWT, cero Docker, cero Prometheus, cero 429
- [ ] 3–6 learning points en español **simple** para EsrgaN (qué es `sent` vs `PENDING`, por qué COUNT y no sumar en Python, por qué no 404 vacío, por qué un servicio sin cola, por qué no Prometheus, por qué insertar `SENT` en tests)
- [ ] Commits hechos o mensajes esperando a EsrgaN

**Prohibido al terminar:** worker Celery, `import twilio`, Token Bucket, Compose, mapper de transiciones, campo `pending` en el JSON.

---

## 5. Qué sigue (no implementar)

Siguiente `PLAN.md` (otra reescritura): **Rate limit** — Token Bucket en Redis **Homebrew**, atómico, por API key (fallback IP), HTTP **429** + `Retry-After`. Eso va **antes** de persist/enqueue. No implementar Redis, 429 ni Celery en este turno.
