# STATUS.md — foto técnica (qué hay / qué no)

Última actualización: **Fases 1–7 hechas en código.** [`PLAN.md`](../PLAN.md) sigue describiendo la Fase 7 (Metrics) hasta que EsrgaN la reescriba; la implementación **ya está**. Siguiente fase = **8 Token Bucket Redis + 429**.  
`pytest -q` → **76 passed**. `ruff check app tests` limpio.

## Escala (no olvidar)

Un microservicio acotado: ~5–20 apps cliente, miles de notificaciones/día. Un proceso FastAPI + (más adelante) un worker Celery + Postgres 14 local + Redis local. **No** Kafka, **no** Kubernetes, **no** JWT de usuarios, **no** frontend.

Desarrollo **local-first**: `uv` venv. Docker Compose es la **última** fase, una sola vez.

## Qué está construido

| Pieza | Dónde | Comportamiento |
| --- | --- | --- |
| Paquete + venv | `pyproject.toml`, `.venv/` | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg, pytest, ruff. Sin Celery/Redis libs. |
| App factory | `app/main.py` | `create_app()`, lifespan: logs + engine/session_factory + cola in-memory, handlers 401/404/503, routers health + clients + notifications + metrics. |
| Health | `GET /health` | 200 `{"status":"ok"}`. Sin prefijo `/api/v1`. **Sin** API key. Sin I/O a Postgres. |
| Auth | `X-API-Key` | `app/core/security.py` (SHA-256), `ClientRepository`, `app/api/deps.py`, `GET /api/v1/clients/me` → 200 `{id,name}` o 401 uniforme. |
| Accept send | `POST /api/v1/notifications/send` | Auth → validar body → persistir `PENDING` → `commit` → `enqueue(id)` → **202** `{notification_id, status}`. Replay de `idempotency_key` → misma fila, sin segundo enqueue. |
| Status | `GET /api/v1/notifications/{id}/status` | 200 `{notification_id, status}` si es del cliente. Missing o de otro cliente → **mismo** 404 `not_found`. |
| Metrics | `GET /api/v1/metrics` | Auth → **200** `{sent, failed}` (conteos Postgres `SENT`/`FAILED` del cliente). Historial vacío o solo `PENDING` → `{"sent":0,"failed":0}` (nunca 404). `POST /send` no incrementa `sent`. |
| Cola (puerto) | `app/services/queue.py` | Protocol `NotificationQueue` + `InMemoryNotificationQueue` (lista en RAM, `app.state`). **No** Celery. |
| Servicios | `app/services/` | `NotificationService` (accept + status; aquí está el `commit`). `MetricsService` (solo lectura; no cola, no `commit`). |
| Settings | `app/core/config.py` | Obliga `SECRET_KEY` (≥16) y `DATABASE_URL` (`SecretStr`, prefijo `postgresql+psycopg://`). **No** hay `REDIS_URL` todavía. |
| DB helpers | `app/core/db.py` | Engine sync + `sessionmaker` (`pool_pre_ping`, `autoflush=False`). |
| Modelos | `app/models/` | `Client`, `Notification` (Mapped). Enums de dominio como VARCHAR. Índice único parcial de idempotencia. |
| Repositorios | `app/repositories/` | `ClientRepository` + `NotificationRepository` (create, get by id+client, get by idempotency, `COUNT` sent/failed por `client_id`). |
| Migraciones | `alembic/` | Revisión `a1b2c3d4e5f6` crea `clients` + `notifications`. URL desde Settings. Cero `create_all`. Sin revisión nueva en Fase 7. |
| Logs | `app/core/logging.py` | stdlib. Texto en local/test, JSON en production. Send: `notification_accepted` / `notification_idempotent_replay` / `notification_status_read`. Metrics: `metrics_read` (`client_id`, `sent`, `failed`; nunca payload ni recipient). |
| Request id | `app/api/middleware/request_id.py` | Header `X-Request-ID` in/out + `ContextVar`. |
| Dominio | `app/domain/` | `Channel`, `NotificationStatus`, máquina de transiciones, `NotificationNotFound`. Stdlib only (no importa SQLAlchemy). |
| Tests | `tests/` | Unit (config, logging, dominio, security, queue, schemas, service fakes) + integración API/auth/send/metrics + persistencia (Postgres real + Alembic). |
| Postgres en la máquina | Homebrew | `psql (PostgreSQL) 14.19`. Bases: `notifications_engine` (app) y `notifications_engine_test` (tests). |

## Qué no existe (no lo inventes)

- `ClientService`, alta HTTP de clientes
- Redis, Token Bucket, 429
- Celery, providers, DLQ
- Dockerfile / Compose
- Mapper HTTP de `InvalidStatusTransition` (esta fase no transiciona)
- JWT / OAuth / `passlib` / bcrypt
- Prometheus / Grafana / `/metrics` en texto `sent_total`

## Arranque local (hoy)

```bash
cp .env.example .env          # SECRET_KEY ≥ 16 + DATABASE_URL psycopg
createdb notifications_engine
createdb notifications_engine_test
source .venv/bin/activate
alembic upgrade head
# seed un cliente (ver README) y guarda la key en claro una vez
uvicorn app.main:app --reload --port 8000
curl -i http://127.0.0.1:8000/health
curl -i -H "X-API-Key: PASTE_RAW_KEY" http://127.0.0.1:8000/api/v1/clients/me
curl -i -H "X-API-Key: PASTE_RAW_KEY" -H "Content-Type: application/json" \
  -d '{"channel":"email","recipient":"user@example.com","template":"welcome"}' \
  http://127.0.0.1:8000/api/v1/notifications/send
curl -i -H "X-API-Key: PASTE_RAW_KEY" http://127.0.0.1:8000/api/v1/metrics
pytest -q
```

## Decisiones ya cerradas (no reabrirlas en una fase)

- Idioma: enseñar en español simple; código/commits en inglés.
- Auth de clientes = API Key, no JWT. Hash = SHA-256 determinista (no bcrypt).
- Envío = cola (Celery), no `BackgroundTasks`, no envío en el request. Hoy el puerto es in-memory.
- Rate limit = Token Bucket en Redis, no dict en memoria.
- Health sin versionar; producto bajo `/api/v1/`.
- Postgres Homebrew 14 en local; Compose al final.
- `PLAN.md` = una fase; se reemplaza, no se concatena.
- Transiciones: `PENDING → PROCESSING → SENT|FAILED`, y `PROCESSING → PENDING` (reintento). `SENT` y `FAILED` son terminales. `PENDING → SENT` es ilegal.
- Enums en BD = VARCHAR (`native_enum=False`), no `ENUM` nativo de Postgres.
- Schema solo vía Alembic (nunca `create_all` en app/tests).
- 401 de auth: mismo cuerpo si falta key, es desconocida o el cliente está inactivo.
- Accept send: `commit` primero, luego `enqueue`. Replay de idempotencia → 202 con la fila original, sin segundo enqueue. 404 idéntico para missing y foreign.
- Metrics: `sent`/`failed` = filas `SENT`/`FAILED` del cliente autenticado. `PENDING`/`PROCESSING` no cuentan. Vacío → 200 con ceros, nunca 404. Fuente = `COUNT` en Postgres, no Redis ni RAM.

## Capas (quién importa a quién)

```text
api  → schemas, services, core (deps puede tocar repositories)
services → domain, repositories, puertos
domain → nada de infra
models → domain + SQLAlchemy
repositories → models + SQLAlchemy
workers → domain + puertos de provider (aún no)
```

FastAPI no envía la notificación. El worker no expone HTTP. Routers no importan `app.models`.

## Qué sigue

Siguiente fase = **8 Token Bucket** en Redis Homebrew + HTTP 429. Todavía no hay Celery. No marcar Fase 8 como hecha.
