# STATUS.md — foto técnica (qué hay / qué no)

Última actualización: **Fases 1–10 hechas en código**. Rama `feat/phase-10-retries-dlq` (parte de `feat/phase-9-celery-worker` = `a602b2b`).  
`origin/main` sigue en `03c28d6` (fases 1–8); Phase 9 **no** está mergeada ahí.  
[`PLAN.md`](../PLAN.md) describe la **Fase 10** (retries + DLQ) — **implementada en código**. Siguiente trabajo = Fase **11** (README / curl polish). **No marcar Fase 11 como hecha. No Compose.**

## Escala (no olvidar)

Un microservicio acotado: ~5–20 apps cliente, miles de notificaciones/día. Un proceso FastAPI + un worker Celery en el **mismo venv** + Postgres 14 local + **un** Redis local (índice 0 = cubo, índice 1 = broker). **No** Kafka, **no** Kubernetes, **no** JWT de usuarios, **no** frontend.

Desarrollo **local-first**: `uv` venv. Docker Compose es la **última** fase, una sola vez.

## Qué está construido

| Pieza | Dónde | Comportamiento |
| --- | --- | --- |
| Paquete + venv | `pyproject.toml`, `.venv/` | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg, redis, **celery[redis]**, pytest, ruff, fakeredis (dev). |
| App factory | `app/main.py` | `create_app()`, lifespan: logs + engine/session_factory + cola **InMemory** si `ENVIRONMENT=test`, **CeleryNotificationQueue** si local/production + Redis/FakeRedis + TokenBucket, handlers 401/404/503 (cola), middleware request-id + rate-limit, routers health + clients + notifications + metrics. |
| Health | `GET /health` | 200 `{"status":"ok"}`. Sin prefijo `/api/v1`. **Sin** API key. Sin I/O a Postgres, Redis **ni Celery** (liveness del proceso, no readiness). |
| Auth | `X-API-Key` | `app/core/security.py` (SHA-256), `ClientRepository`, `app/api/deps.py`, `GET /api/v1/clients/me` → 200 `{id,name}` o 401 uniforme. |
| Rate limit | `POST /api/v1/notifications/send` | Token Bucket Redis (Lua, atómico). Default **10/min** por API key (`rl:key:{sha256}`) o IP si no hay header. Requests 1–10 → 202. El 11º → **429** `{detail, code: rate_limited}` + `Retry-After`. Redis caído → **503** limiter, **cero** fila. `/health`, `/me`, `/status`, `/metrics` no gastan fichas. Cubo = índice **0**. |
| Accept send | `POST /api/v1/notifications/send` | Limiter → auth → validar body → persistir `PENDING` → `commit` → `enqueue(id)` → **202** `{notification_id, status}`. Replay de `idempotency_key` → misma fila, sin segundo enqueue (sí gasta ficha). El HTTP **no** envía. **No espera** backoff. |
| Status | `GET /api/v1/notifications/{id}/status` | 200 `{notification_id, status}` si es del cliente (`PENDING`/`PROCESSING`/`SENT`/`FAILED`). Missing o de otro cliente → **mismo** 404 `not_found`. Durante espera de retry la fila vuelve a `PENDING`. |
| Metrics | `GET /api/v1/metrics` | Auth → **200** `{sent, failed}` (conteos Postgres `SENT`/`FAILED` del cliente). Historial vacío o solo `PENDING` → `{"sent":0,"failed":0}` (nunca 404). `POST /send` no incrementa `sent`; `failed` sube **solo** cuando la fila es `FAILED`, no en cada reintento. |
| Cola (puerto) | `app/services/queue.py` | Protocol `NotificationQueue`. `InMemoryNotificationQueue` en pytest. `CeleryNotificationQueue` en local/prod: `apply_async(args=[str(id)], queue="notifications")`. Broker caído → `QueueUnavailableError` → HTTP **503**; la fila `PENDING` **sí** queda. |
| Worker | `app/workers/` | Celery app (`celery_app.py`, colas `notifications` + `notifications.dlq`), task `notifications.deliver` (`bind=True`, UUID string), `notifications.dead_letter` (solo log), `apply_delivery_result` mapea RETRY→`self.retry` y FAILED→publish DLQ. Arranque: `celery -A app.workers.celery_app worker --queues=notifications,notifications.dlq`. **No** importa routers. |
| Dispatch | `app/services/dispatch.py` | `DispatchService` + `DeliveryRetryPolicy`: `PENDING → PROCESSING` (commit) → `provider.send` → `SENT`, o transiente `PROCESSING → PENDING` + countdown, o permanente/agotado `FAILED` + `dead_letter`. Skip si ya `SENT`/`FAILED`. Si ya `PROCESSING`, reintenta el send. Missing id → log y `MISSING`. Devuelve `DispatchResult` (no importa Celery). |
| Retry + DLQ | dominio + worker | Presupuesto **5** intentos (`max_delivery_attempts`). Backoff **5s, 15s, 45s** (tope 45s). Transiente / `ProviderError` pelado / `Exception` → retry. `PermanentProviderError` → `FAILED` + DLQ **sin** backoff. Cola nombrada `notifications.dlq` (Redis-as-broker **no** tiene DLX). Postgres `FAILED` es la fuente de verdad. |
| Provider | `app/providers/` | Protocol `NotificationProvider` + `SimulatedNotificationProvider`. Template exacto `fail-transient` → `TransientProviderError`. `fail-permanent` → `PermanentProviderError`. Cualquier otro (p. ej. `welcome`) acierta. Cero `random`. Cero Twilio/Mailtrap. |
| Servicios | `app/services/` | `NotificationService` (accept + status; `commit` en accept). `DispatchService` (worker; `commit` en dispatch). `MetricsService` (solo lectura). `accept` **no** conoce Redis ni Celery. |
| Settings | `app/core/config.py` | Obliga `SECRET_KEY` (≥16), `DATABASE_URL` (`SecretStr`, prefijo `postgresql+psycopg://`), `REDIS_URL` (`SecretStr`, prefijo `redis://`) y `CELERY_BROKER_URL` (`SecretStr`, prefijo `redis://`). `rate_limit_per_minute` default 10, `ge=1`. `max_delivery_attempts` default 5, `ge=1`. `delivery_retry_countdowns` default `(5, 15, 45)` desde CSV env; vacío o enteros `< 1` → `ValidationError`. |
| Token Bucket | `app/core/rate_limit.py` | Script Lua `EVAL`: refill continuo + consume 1 ficha. Reloj `now_ms` inyectable. Middleware en `app/api/middleware/rate_limit.py`. |
| DB helpers | `app/core/db.py` | Engine sync + `sessionmaker` (`pool_pre_ping`, `autoflush=False`). Worker usa el mismo helper vía `app/workers/runtime.py` (lazy singleton). |
| Modelos | `app/models/` | `Client`, `Notification` (Mapped). Enums de dominio como VARCHAR. Índice único parcial de idempotencia. `Client.rate_limit_per_minute` existe, **no cableado**. `retry_count` ya existía (cero Alembic en Fase 10). |
| Repositorios | `app/repositories/` | `ClientRepository` + `NotificationRepository` (create, get by id+client, **get_by_id** sin client_id para el worker, get by idempotency, `COUNT` sent/failed por `client_id`). |
| Migraciones | `alembic/` | Revisión `a1b2c3d4e5f6` crea `clients` + `notifications`. URL desde Settings. Cero `create_all`. Sin revisión nueva en Fase 10. |
| Logs | `app/core/logging.py` | stdlib. Texto en local/test, JSON en production. Send: `notification_accepted` / `notification_idempotent_replay` / `notification_status_read`. Dispatch: `notification_dispatch_started` / `notification_sent` / `notification_dispatch_skipped` / `notification_dispatch_failed` / `notification_dispatch_missing` / `notification_retry_scheduled` / `simulated_send`. Worker: `notification_dead_lettered` / `notification_dlq_publish_failed`. Metrics: `metrics_read`. Limiter: `rate_limit_allowed` / `rate_limit_exceeded` / `rate_limit_store_unavailable`. Nunca API key ni payload completo. |
| Request id | `app/api/middleware/request_id.py` | Header `X-Request-ID` in/out + `ContextVar`. También sale en un 429 (middleware más externo). |
| Dominio | `app/domain/` | `Channel`, `NotificationStatus`, máquina de transiciones, `NotificationNotFound`, **`DeliveryRetryPolicy`**. Stdlib only (no importa SQLAlchemy, Redis ni Celery). |
| Tests | `tests/` | Unit (config broker + CSV backoff, logging, dominio + retry policy, security, queue in-memory, celery queue con fake `apply_async`, schemas, Token Bucket, provider simulado fail templates, dispatch retry/permanente/agotado, `apply_delivery_result`) + integración API/auth/send/metrics/429 + persistencia + dispatch Postgres (transiente→SENT, permanente→FAILED). HTTP usa FakeRedis + InMemory queue (`ENVIRONMENT=test`); **no** exige worker Celery vivo. Cero `time.sleep`. Cero `task_always_eager` global. |
| Postgres en la máquina | Homebrew | `psql (PostgreSQL) 14.19`. Bases: `notifications_engine` (app) y `notifications_engine_test` (tests). |
| Redis en la máquina | Homebrew | Índice **0** Token Bucket (`REDIS_URL`). Índice **1** broker Celery (`CELERY_BROKER_URL`). Un solo `redis-server`. Tests HTTP **no** necesitan el daemon. |

## Qué no existe (no lo inventes)

- `ClientService`, alta HTTP de clientes
- Celery Beat, UI de replay admin
- Mailtrap / Twilio reales (`import twilio` prohibido)
- Cablear `Client.rate_limit_per_minute` (sigue el default global)
- Dockerfile / Compose
- Mapper HTTP de `InvalidStatusTransition` (HTTP no transiciona; el worker usa la máquina, sin mapper HTTP)
- JWT / OAuth / `passlib` / bcrypt
- Prometheus / Grafana / `/metrics` en texto `sent_total`
- `BackgroundTasks`, `task_always_eager` por defecto, result backend Redis
- Columna `dead_lettered_at`

## Arranque local (hoy)

```bash
cp .env.example .env          # SECRET_KEY ≥ 16 + DATABASE_URL psycopg + REDIS_URL + CELERY_BROKER_URL
brew services start redis && redis-cli ping
createdb notifications_engine
createdb notifications_engine_test
source .venv/bin/activate
alembic upgrade head
# seed un cliente (ver README) y guarda la key en claro una vez
# terminal 1
uvicorn app.main:app --reload --port 8000
# terminal 2 (mismo venv)
celery -A app.workers.celery_app worker --loglevel=INFO --queues=notifications,notifications.dlq
curl -i http://127.0.0.1:8000/health
curl -i -H "X-API-Key: PASTE_RAW_KEY" http://127.0.0.1:8000/api/v1/clients/me
curl -i -H "X-API-Key: PASTE_RAW_KEY" -H "Content-Type: application/json" \
  -d '{"channel":"email","recipient":"user@example.com","template":"welcome"}' \
  http://127.0.0.1:8000/api/v1/notifications/send
# poll GET /status hasta SENT; GET /metrics → sent: 1
# "template":"fail-transient" → retries 5s/15s/45s/45s luego FAILED + log DLQ
# "template":"fail-permanent" → FAILED al primer golpe
# sin el proceso worker, GET /status se queda PENDING
# el 11º POST /send en el mismo minuto → 429 + Retry-After
pytest -q
```

## Decisiones ya cerradas (no reabrirlas en una fase)

- Idioma: enseñar en español simple; código/commits en inglés.
- Auth de clientes = API Key, no JWT. Hash = SHA-256 determinista (no bcrypt).
- Envío = cola Celery, no `BackgroundTasks`, no envío en el request. Pytest usa InMemory; local/prod usa `CeleryNotificationQueue`.
- Broker Celery = Redis índice **1**. Token Bucket = índice **0**. Mismo servidor, URLs explícitas.
- Payload de la task = UUID en string. El worker carga la fila desde Postgres.
- Provider = puerto + simulado. El adapter **clasifica** transiente vs permanente; **no** reintenta. La decisión vive en `DeliveryRetryPolicy` + `DispatchService`; Celery solo obedece.
- Rate limit = Token Bucket en Redis (Lua atómico), no dict en memoria. Solo `POST /send`. 10/min default. Cubo por hash de API key (o IP si no hay header). 429 gana a 401. Redis caído → 503, no fallback en RAM. Health no hace ping a Redis.
- Health sin versionar; producto bajo `/api/v1/`.
- Postgres Homebrew 14 en local; Redis Homebrew; Compose al final.
- `PLAN.md` = una fase; se reemplaza, no se concatena.
- Transiciones: `PENDING → PROCESSING → SENT|FAILED`, y `PROCESSING → PENDING` (reintento). `SENT` y `FAILED` son terminales. `PENDING → SENT` es ilegal.
- Enums en BD = VARCHAR (`native_enum=False`), no `ENUM` nativo de Postgres.
- Schema solo vía Alembic (nunca `create_all` en app/tests).
- 401 de auth: mismo cuerpo si falta key, es desconocida o el cliente está inactivo.
- Accept send: `commit` primero, luego `enqueue`. Replay de idempotencia → 202 con la fila original, sin segundo enqueue. 404 idéntico para missing y foreign.
- Metrics: `sent`/`failed` = filas `SENT`/`FAILED` del cliente autenticado. `PENDING`/`PROCESSING` no cuentan. Vacío → 200 con ceros, nunca 404. Fuente = `COUNT` en Postgres, no Redis ni RAM.
- Dispatch posee el `commit`. Task tonta (solo id). Transiente → `PENDING` + countdown. Permanente o 5.º fallo → `FAILED` + publish `notifications.dlq`.
- Backoff: 5s/15s/45s con tope 45s (no 135s). 5 intentos = 1 inicial + 4 `self.retry` (`max_retries=max_attempts-1`).
- DLQ = cola Kombu nombrada. Redis-as-broker no tiene dead-letter exchange.

## Capas (quién importa a quién)

```text
api  → schemas, services, core (deps puede tocar repositories)
services → domain, repositories, puertos (cola, provider)
domain → nada de infra
models → domain + SQLAlchemy
repositories → models + SQLAlchemy
workers → services/dispatch + provider simulado + repositories (no routers)
providers → domain (Channel); no FastAPI, no Celery retry
core/rate_limit → Redis (no FastAPI, no modelos)
```

FastAPI no envía la notificación. El worker no expone HTTP. Routers no importan `app.models` ni `app.workers`. El router de send no importa Redis ni Celery. `DispatchService` no importa Celery.

## Qué sigue

Siguiente trabajo = **reescribir** [`PLAN.md`](../PLAN.md) para la Fase **11** (README / curl polish: runbook local). Retries + DLQ ya están. **No implementar Beat, Compose (12) ni providers reales en el turno de polish.**
