# STATUS.md — foto técnica (qué hay / qué no)

Última actualización: **Fase 5 cerrada en código** (`feat/phase-5-api-keys`).  
Base: `origin/main` = `be14f38` (PR **#5**).  
`pytest -q` debe incluir los 33 de Fases 2–4 más security + repository + auth HTTP. `ruff check app tests` limpio.

El [`PLAN.md`](../PLAN.md) actual sigue describiendo la Fase 5 (no reescribir todavía a Fase 6 hasta que EsrgaN lo pida).

## Escala (no olvidar)

Un microservicio acotado: ~5–20 apps cliente, miles de notificaciones/día. Un proceso FastAPI + (más adelante) un worker Celery + Postgres 14 local + Redis local. **No** Kafka, **no** Kubernetes, **no** JWT de usuarios, **no** frontend.

Desarrollo **local-first**: `uv` venv. Docker Compose es la **última** fase, una sola vez.

## Qué está construido

| Pieza | Dónde | Comportamiento |
| --- | --- | --- |
| Paquete + venv | `pyproject.toml`, `.venv/` | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg, pytest, ruff. Sin Celery/Redis libs. |
| App factory | `app/main.py` | `create_app()`, lifespan: logs + engine/session_factory, handler 401, routers health + clients. |
| Health | `GET /health` | 200 `{"status":"ok"}`. Sin prefijo `/api/v1`. **Sin** API key. Sin I/O a Postgres. |
| Auth | `X-API-Key` | `app/core/security.py` (SHA-256), `ClientRepository`, `app/api/deps.py`, `GET /api/v1/clients/me` → 200 `{id,name}` o 401 uniforme. |
| Settings | `app/core/config.py` | Obliga `SECRET_KEY` (≥16) y `DATABASE_URL` (`SecretStr`, prefijo `postgresql+psycopg://`). **No** hay `REDIS_URL` todavía. |
| DB helpers | `app/core/db.py` | Engine sync + `sessionmaker` (`pool_pre_ping`, `autoflush=False`). |
| Modelos | `app/models/` | `Client`, `Notification` (Mapped). Enums de dominio como VARCHAR. Índice único parcial de idempotencia. |
| Repositorio | `app/repositories/client_repository.py` | `get_by_hashed_api_key` solamente. |
| Migraciones | `alembic/` | Revisión que crea `clients` + `notifications`. URL desde Settings. Cero `create_all`. Sin revisión nueva en Fase 5. |
| Logs | `app/core/logging.py` | stdlib. Texto en local/test, JSON en production. Auth: `api_key_rejected` / `client_authenticated` (nunca la key en claro). |
| Request id | `app/api/middleware/request_id.py` | Header `X-Request-ID` in/out + `ContextVar`. |
| Dominio | `app/domain/` | `Channel`, `NotificationStatus`, máquina de transiciones. Stdlib only (no importa SQLAlchemy). |
| Tests | `tests/` | Unit (config, logging, dominio, security) + integración API/auth + persistencia (Postgres real + Alembic). |
| Postgres en la máquina | Homebrew | `psql (PostgreSQL) 14.19`. Bases: `notifications_engine` (app) y `notifications_engine_test` (tests). |

## Qué no existe (no lo inventes)

- `POST /api/v1/notifications/send`, status, métricas
- `NotificationRepository`, `ClientService`, alta HTTP de clientes
- Redis, Token Bucket, 429
- Celery, providers, DLQ
- Dockerfile / Compose
- Mapper HTTP de excepciones de dominio (`InvalidStatusTransition` etc.)
- JWT / OAuth / `passlib` / bcrypt

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
pytest -q
```

## Decisiones ya cerradas (no reabrirlas en una fase)

- Idioma: enseñar en español simple; código/commits en inglés.
- Auth de clientes = API Key, no JWT. Hash = SHA-256 determinista (no bcrypt).
- Envío = cola (Celery), no `BackgroundTasks`, no envío en el request.
- Rate limit = Token Bucket en Redis, no dict en memoria.
- Health sin versionar; producto bajo `/api/v1/`.
- Postgres Homebrew 14 en local; Compose al final. (La rule `postgresql.mdc` cita 16; **gana `AGENTS.md`**: 14.x.)
- `PLAN.md` = una fase; se reemplaza, no se concatena.
- Transiciones: `PENDING → PROCESSING → SENT|FAILED`, y `PROCESSING → PENDING` (reintento). `SENT` y `FAILED` son terminales. `PENDING → SENT` es ilegal.
- Enums en BD = VARCHAR (`native_enum=False`), no `ENUM` nativo de Postgres.
- Schema solo vía Alembic (nunca `create_all` en app/tests).
- 401 de auth: mismo cuerpo si falta key, es desconocida o el cliente está inactivo.

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

Después de cerrar Fase 5 (este código), la siguiente reescritura de `PLAN.md` es **Accept send**: persistir `PENDING` + **puerto de cola** (interfaz, no Celery real) + `202 Accepted`. Auth de esta fase se reutiliza. Todavía no hay worker ni Mailtrap.
