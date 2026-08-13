# STATUS.md — foto técnica (qué hay / qué no)

Última actualización: **después de la Fase 3** (rama `feat/phase-3-domain`, sobre `e4f8589`).  
Cuando la Fase 4 cierre, el agente de esa fase **debe** editar este archivo (está en el `PLAN.md`).

## Escala (no olvidar)

Un microservicio acotado: ~5–20 apps cliente, miles de notificaciones/día. Un proceso FastAPI + (más adelante) un worker Celery + Postgres 14 local + Redis local. **No** Kafka, **no** Kubernetes, **no** JWT de usuarios, **no** frontend.

Desarrollo **local-first**: `uv` venv. Docker Compose es la **última** fase, una sola vez.

## Qué está construido

| Pieza | Dónde | Comportamiento |
| --- | --- | --- |
| Paquete + venv | `pyproject.toml`, `.venv/` | Python 3.12, FastAPI, pytest, ruff. Sin Celery/SQLAlchemy/Redis libs. |
| App factory | `app/main.py` | `create_app()`, `app = create_app()` al importar. Lifespan configura logs. |
| Health | `GET /health` | 200 `{"status":"ok"}`. Sin prefijo `/api/v1`. |
| Settings | `app/core/config.py` | Obliga `SECRET_KEY` (`SecretStr`, ≥16). `environment`: local\|test\|production. `log_level` se normaliza a mayúsculas. **No** hay `DATABASE_URL` ni `REDIS_URL` todavía (no hay IO). |
| Logs | `app/core/logging.py` | stdlib. Texto en local/test, JSON en production. Extra: `request_id`, y más adelante `notification_id`, `client_id`, `channel`, `status`, `retry_count`. |
| Request id | `app/api/middleware/request_id.py` | Header `X-Request-ID` in/out + `ContextVar`. |
| Dominio | `app/domain/` | `Channel` (email/sms/push/webhook). `NotificationStatus` (`PENDING`/`PROCESSING`/`SENT`/`FAILED`). Máquina: `can_transition` / `assert_transition` / `transition`. `DomainError` + `InvalidStatusTransition`. Stdlib only. |
| Tests | `tests/` | Fase 2 (health, config, logging, request id) + `tests/unit/domain/` (enums + transiciones legales/ilegales). Cero `TestClient` en dominio. |

## Qué no existe (no lo inventes)

- `POST /api/v1/notifications/send`, status, métricas
- SQLAlchemy, Alembic, tablas
- Auth `X-API-Key` (hashed)
- Redis, Token Bucket, 429
- Celery, providers, DLQ
- Dockerfile / Compose
- Mapper HTTP de excepciones de dominio

## Arranque local (hoy)

```bash
cp .env.example .env          # SECRET_KEY ≥ 16
source .venv/bin/activate
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
- Postgres Homebrew 14 en local; Compose al final.
- `PLAN.md` = una fase; se reemplaza, no se concatena.
- Transiciones: `PENDING → PROCESSING → SENT|FAILED`, y `PROCESSING → PENDING` (reintento). `SENT` y `FAILED` son terminales. `PENDING → SENT` es ilegal.

## Capas (quién importa a quién)

```text
api  → schemas, services, core
services → domain, repositories, puertos
domain → nada de infra
models/repositories → domain + SQLAlchemy (aún no)
workers → domain + puertos de provider (aún no)
```

FastAPI no envía la notificación. El worker no expone HTTP.

## Qué sigue

**Postgres local + SQLAlchemy 2 Mapped + Alembic.** Las columnas `channel` y `status` usarán estos enums. No hay cola ni `POST /send` todavía.
