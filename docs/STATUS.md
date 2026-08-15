# STATUS.md — foto técnica (qué hay / qué no)

Última actualización: **después de la Fase 4** (rama `feat/phase-4-persistence`).  
`pytest -q` debe pasar unitarios de config/logging/dominio + integración de persistencia (Postgres real).

El [`PLAN.md`](../PLAN.md) actual era la **Fase 4 (persistencia)**. Cuando cierre, EsrgaN reescribe `PLAN.md` entero (ver playbook).

## Escala (no olvidar)

Un microservicio acotado: ~5–20 apps cliente, miles de notificaciones/día. Un proceso FastAPI + (más adelante) un worker Celery + Postgres 14 local + Redis local. **No** Kafka, **no** Kubernetes, **no** JWT de usuarios, **no** frontend.

Desarrollo **local-first**: `uv` venv. Docker Compose es la **última** fase, una sola vez.

## Qué está construido

| Pieza | Dónde | Comportamiento |
| --- | --- | --- |
| Paquete + venv | `pyproject.toml`, `.venv/` | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg, pytest, ruff. Sin Celery/Redis libs. |
| App factory | `app/main.py` | `create_app()`, lifespan: logs + engine/session_factory en `app.state`, `engine.dispose()` al apagar. |
| Health | `GET /health` | 200 `{"status":"ok"}`. Sin prefijo `/api/v1`. **Sin** I/O a Postgres (liveness ≠ readiness). |
| Settings | `app/core/config.py` | Obliga `SECRET_KEY` (≥16) y `DATABASE_URL` (`SecretStr`, prefijo `postgresql+psycopg://`). **No** hay `REDIS_URL` todavía. |
| DB helpers | `app/core/db.py` | Engine sync + `sessionmaker` (`pool_pre_ping`, `autoflush=False`). |
| Modelos | `app/models/` | `Client`, `Notification` (Mapped). Enums de dominio como VARCHAR. Índice único parcial de idempotencia. |
| Migraciones | `alembic/` | Revisión que crea `clients` + `notifications`. URL desde Settings. Cero `create_all`. |
| Logs | `app/core/logging.py` | stdlib. Texto en local/test, JSON en production. |
| Request id | `app/api/middleware/request_id.py` | Header `X-Request-ID` in/out + `ContextVar`. |
| Dominio | `app/domain/` | `Channel`, `NotificationStatus`, máquina de transiciones. Stdlib only (no importa SQLAlchemy). |
| Tests | `tests/` | Unit (config, logging, dominio) + integración API + `tests/integration/test_persistence.py` (Postgres real + Alembic). |
| Postgres en la máquina | Homebrew | `psql (PostgreSQL) 14.19`. Bases: `notifications_engine` (app) y `notifications_engine_test` (tests). |

## Qué no existe (no lo inventes)

- `POST /api/v1/notifications/send`, status, métricas
- Auth `X-API-Key` (hash/verify helpers) — la columna `hashed_api_key` ya existe; la lógica llega en Fase 5
- Repositorios / `app/api/deps.py`
- Redis, Token Bucket, 429
- Celery, providers, DLQ
- Dockerfile / Compose
- Mapper HTTP de excepciones de dominio

## Arranque local (hoy)

```bash
cp .env.example .env          # SECRET_KEY ≥ 16 + DATABASE_URL psycopg
createdb notifications_engine
createdb notifications_engine_test
source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload --port 8000
curl -i http://127.0.0.1:8000/health
pytest -q
```

## Decisiones ya cerradas (no reabrirlas en una fase)

- Idioma: enseñar en español simple; código/commits en inglés.
- Auth de clientes = API Key, no JWT.
- Envío = cola (Celery), no `BackgroundTasks`, no envío en el request.
- Rate limit = Token Bucket en Redis, no dict en memoria.
- Health sin versionar; producto bajo `/api/v1/`.
- Postgres Homebrew 14 en local; Compose al final. (La rule `postgresql.mdc` cita 16; **gana `AGENTS.md`**: 14.x.)
- `PLAN.md` = una fase; se reemplaza, no se concatena.
- Transiciones: `PENDING → PROCESSING → SENT|FAILED`, y `PROCESSING → PENDING` (reintento). `SENT` y `FAILED` son terminales. `PENDING → SENT` es ilegal.
- Enums en BD = VARCHAR (`native_enum=False`), no `ENUM` nativo de Postgres.
- Schema solo vía Alembic (nunca `create_all` en app/tests).

## Capas (quién importa a quién)

```text
api  → schemas, services, core
services → domain, repositories, puertos
domain → nada de infra
models → domain + SQLAlchemy
workers → domain + puertos de provider (aún no)
```

FastAPI no envía la notificación. El worker no expone HTTP.

## Qué sigue

Siguiente fase (otra reescritura de `PLAN.md`): **API keys** — hash de la key en reposo + FastAPI `Depends` que lee `X-API-Key` y carga el `Client`. Todavía no hay cola ni `POST /send`.
