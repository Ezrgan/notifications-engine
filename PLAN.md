# PLAN.md — Fase 5: API keys (`X-API-Key` + hash en reposo + Depends)

> **REGLA OBLIGATORIA PARA TODOS LOS AGENTES:**
> Antes de ejecutar cualquier paso, leer y acatar [`AGENTS.md`](./AGENTS.md), [`.cursor/rules/`](./.cursor/rules/) (sobre todo `fastapi.mdc`, `postgresql.mdc` y `testing.mdc`) y [`docs/HOW_TO_WRITE_THE_NEXT_PLAN.md`](./docs/HOW_TO_WRITE_THE_NEXT_PLAN.md).
> Este archivo es el **único plan ejecutable**. Describe **una sola fase**. Cuando cierre, EsrgaN **reescribe** `PLAN.md` entero (ver el playbook en `docs/`).
> No implementar `POST /send`, cola, Celery, Redis, Token Bucket, métricas, mapper HTTP de excepciones de dominio, JWT ni Docker.

> **Cómo está pensado este documento:**
> Un agente debe poder implementarlo **sin inventar**. Cada paso: archivos exactos, contrato, tests, commit propuesto, qué no tocar.
> Código completo. Cero placeholders. Cero `# ... rest of code ...`.
> Enseñar a EsrgaN en **español simple**, con ejemplos. Sin jerga sin definir.

> **Estado de partida (verificado):**
> `origin/main` = `be14f38` — squash merge del PR **#5** (`feat: persist clients and notifications on local Postgres (#5)`). Fase 4 **sí** está en `main` remoto.
> El `main` **local** puede seguir en `9a57e86` hasta un `git checkout main && git pull` (estaba 1 commit atrás al escribir el PLAN).
> `feat/phase-4-persistence` = `2116005` (mismo *tree* que `be14f38`; el SHA cambia por el squash).
> `pytest -q` → **33 passed**. `ruff check app tests` limpio.
> Hay tablas `clients` / `notifications`, columna `hashed_api_key`, engine en el lifespan. **No** existe `app/core/security.py` ni `app/api/deps.py`. El único router público es `GET /health`. Cero JWT, cero Redis, cero Docker.

---

## 0. Decisiones congeladas (esta fase)

| # | Decisión | Valor congelado |
| --- | --- | --- |
| D1 | Idea de la fase | Las apps cliente se autentican con una **API key** en el header `X-API-Key`. En Postgres **solo** vive el hash. Un `Depends` carga el `Client`. Cero envío, cero cola. |
| D2 | Hash | `hashlib.sha256(raw.encode("utf-8")).hexdigest()` (stdlib). 64 caracteres hex. Cabe en `hashed_api_key` `String(255)` **sin** migración. |
| D3 | Por qué no bcrypt / Argon2 | Esos algoritmos usan **sal distinta cada vez**. No puedes hacer `SELECT … WHERE hashed_api_key = hash(header)`. Tendrías que recorrer todos los clientes. A esta escala (5–20) “funcionaría”, pero es el patrón equivocado para API keys. |
| D4 | Por qué no HMAC(`SECRET_KEY`) | Si mañana rotas `SECRET_KEY`, **todas** las keys de cliente dejarían de coincidir. La API key ya tiene mucha entropía (`token_urlsafe(32)`): SHA-256 sin sal es suficiente. `SECRET_KEY` sigue existiendo para Settings; **no** entra en el hash. |
| D5 | Formato de la key en claro | `generate_api_key()` → prefijo `ne_` + `secrets.token_urlsafe(32)`. Ejemplo: `ne_xY3…`. El prefijo es para que EsrgaN la reconozca en logs/docs; no es un estándar de la industria. |
| D6 | Header | Exactamente `X-API-Key`. `APIKeyHeader(name="X-API-Key", auto_error=False)`. `auto_error=False` porque FastAPI, si falta la key, a menudo responde **403**; `AGENTS.md` exige **401**. |
| D7 | 401 único | Falta el header, header vacío, key desconocida, **o** cliente `is_active=False` → siempre `401` con el **mismo** cuerpo. Así no filtramos “esta key existió pero la desactivamos”. |
| D8 | Cuerpo de error (solo este 401) | `{"detail": "Invalid or missing API key", "code": "unauthorized"}` más header `WWW-Authenticate: ApiKey`. Los `422` de Pydantic **no** se reescriben en esta fase (el mapper global de dominio sigue prohibido). |
| D9 | Excepción HTTP | `UnauthorizedError` en `app/api/errors.py` + handler en `create_app`. **No** es dominio: no va a `app/domain/exceptions.py`. **No** mapear `InvalidStatusTransition`. |
| D10 | Superficie HTTP | `GET /api/v1/clients/me` → `200` `{"id": "<uuid>", "name": "<str>"}`. Es el **probe** de auth (no está en la tabla §5.1 porque esa tabla asume `/send`). `/health` **sigue público** (sin key). **No** hay `POST` de alta de clientes ni admin. |
| D11 | Capas | `security.py` (core) hashea. `ClientRepository` (persistencia) busca por hash. `deps.py` (composition root) arma sesión + auth. El **router** solo habla schemas + `Depends`. El router **no** importa `app.models`. |
| D12 | `get_db` | Sesión desde `request.app.state.session_factory`. `yield` + `close()` en `finally`. **Cero `commit`** aquí (`AGENTS.md` §6.4: el use case commitea; este path es de lectura). |
| D13 | Repositorio | Solo `get_by_hashed_api_key`. **No** `NotificationRepository`. **No** `ClientService` (`/me` no es un caso de uso de negocio; es “quién eres”). |
| D14 | Schema | `AuthenticatedClient` (`id`, `name`). **No** devolver `hashed_api_key`, `is_active` ni `rate_limit_per_minute` (el limiter es Fase 8). |
| D15 | Settings / Alembic | **No** hay campo nuevo. **No** hay revisión Alembic. `REDIS_URL` sigue ausente. |
| D16 | Libs | **Prohibido** instalar `passlib`, `bcrypt`, `argon2-cffi`, `python-jose`, `PyJWT`, `authlib`. Stdlib alcanza. |
| D17 | Tests | Unitarios de hash **sin** Postgres. Integración HTTP contra Postgres **real** con filas **commiteadas** (el `db_session` con rollback de Fase 4 **no** es visible para `TestClient`: otro pool). Cero `time.sleep`. Cero SQLite. |
| D18 | Logs | Fallo: `api_key_rejected` con `reason=missing` o `unknown_or_inactive`. Éxito: `client_authenticated` con `client_id`. **Nunca** loguear la key en claro, el header, ni el hash. |
| D19 | Git | Rama `feat/phase-5-api-keys` desde `main` actualizado (`be14f38` / PR #5). Commits **solo si EsrgaN lo pide**. |
| D20 | Docker / extras | Prohibidos. No Kafka, JWT, Prisma, Redis, Celery, `BackgroundTasks`. |

---

## 1. Diagnóstico (por qué esta fase)

Archivos reales, no memoria:

1. [`docs/STATUS.md`](docs/STATUS.md) marca Fases 1–4 hechas. [`AGENTS.md`](AGENTS.md) §10.1 siguiente número libre = **5 API keys**. No saltar a `/send` (fase 6): persistir `PENDING` sin saber **qué cliente** es sería una fila huérfana de identidad.
2. [`app/models/client.py`](app/models/client.py) ya tiene `hashed_api_key` UNIQUE y `is_active`. Los tests de persistencia insertan `"dummy-hash-not-a-real-key-…"`. Eso **no** es autenticación: es un string dummy. Falta el puente HTTP → hash → fila.
3. [`app/main.py`](app/main.py) solo monta health. No hay `app/api/deps.py` ni `app/core/security.py`. [`app/repositories/__init__.py`](app/repositories/__init__.py) es un docstring. Esta fase **estrena** el composition root y el primer repositorio.
4. [`app/api/routers/health.py`](app/api/routers/health.py) no pide llave. Debe seguir así: un probe de “¿el proceso vive?” no debe exigir credenciales (los orquestadores no tienen tu API key).
5. Ejemplo de uso: insertas un cliente “checkout-app”, guardas el hash de `ne_abc…`, y haces `curl -H 'X-API-Key: ne_abc…' http://127.0.0.1:8000/api/v1/clients/me`. Ves `{"id":"…","name":"checkout-app"}`. Sin header, `401`. Eso es auth de máquinas, no login de humanos.

---

## 2. Árbol al cerrar esta fase

```text
app/core/security.py                         # NUEVO: generate_api_key, hash_api_key
app/core/config.py                           # no tocar (SECRET_KEY / DATABASE_URL ya obligatorios)
app/repositories/__init__.py                 # EDITAR: reexportar ClientRepository
app/repositories/client_repository.py        # NUEVO
app/api/errors.py                            # NUEVO: UnauthorizedError
app/api/deps.py                              # NUEVO: get_db, get_current_client
app/schemas/client.py                        # NUEVO: AuthenticatedClient
app/api/routers/clients.py                   # NUEVO: GET /api/v1/clients/me
app/main.py                                  # EDITAR: handler 401 + include_router
tests/unit/test_security.py                  # NUEVO
tests/integration/test_client_repository.py  # NUEVO (rollback session, OK)
tests/integration/test_auth.py               # NUEVO (filas commiteadas + TestClient)
tests/integration/conftest.py                # EDITAR solo si hace falta un fixture de seed commiteado
README.md                                    # EDITAR: curl con X-API-Key + cómo sembrar un cliente local
docs/STATUS.md                               # EDITAR en el último paso de implementación
```

**No crear:** `POST /send`, `NotificationRepository`, `ClientService`, `app/core/security.py` extra (pepper, rounds), routers `/api/v1/notifications/`, `Dockerfile`, `docker-compose.yml`, migración Alembic, nada en `app/domain/`.

**No tocar:** máquina de estados, modelos/columnas, `GET /health` payload, `SECRET_KEY` / `DATABASE_URL` validators, `create_all`.

---

## 3. Git

Fase 4 ya está en `origin/main` (PR #5, squash `be14f38`). Crear la rama de Fase 5 **desde `main`**, no desde la feature vieja:

```bash
git checkout main
git pull
# HEAD esperado: be14f38  (mensaje … (#5))
git checkout -b feat/phase-5-api-keys
```

Antes de cerrar cada paso de código:

```bash
source .venv/bin/activate
pytest -q
ruff check app tests
```

Los 33 tests de Fases 2–4 deben seguir verdes (más los nuevos de esta fase).

---

## FASE 0 — Preparación

- [ ] `pytest -q` → 33 passed **antes** de editar
- [ ] `ruff check app tests` limpio
- [ ] Postgres local sigue arriba (`psql -d notifications_engine_test -c 'SELECT 1'`)
- [ ] Rama `feat/phase-5-api-keys` creada desde `main` (`be14f38` / PR #5)
- [ ] Cero Docker, cero Compose, cero `uv pip install` de libs de auth
- [ ] Enseñar a EsrgaN (ejemplo): una **API key** es una contraseña de **aplicación**, no de persona. Stripe te da `sk_live_…`; tú se la pones a tu backend. Aquí el header se llama `X-API-Key`. JWT sería un carnet temporal de un humano después de login — no aplica.

---

## FASE 5 — API keys

### Paso 5.1 — Hash y generación (stdlib)

Crear [`app/core/security.py`](app/core/security.py). Responsabilidad única: generar la key en claro y hashearla. Quién lo llama: tests, el snippet del README, y `get_current_client`. Nadie más implementa SHA-256 por su cuenta.

```python
"""API key generation and hashing.

Raw keys never persist. SHA-256 is deterministic so we can look up a client
with one indexed SELECT. Do not switch to bcrypt: unique salts cannot be queried.
"""

from __future__ import annotations

import hashlib
import secrets

_API_KEY_PREFIX = "ne_"
_TOKEN_BYTES = 32


def generate_api_key() -> str:
    """Return a high-entropy key. Show it once; store only hash_api_key(raw)."""
    return f"{_API_KEY_PREFIX}{secrets.token_urlsafe(_TOKEN_BYTES)}"


def hash_api_key(raw_api_key: str) -> str:
    """Return the hex SHA-256 of the raw key (64 chars). Never log raw_api_key."""
    return hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest()
```

Crear [`tests/unit/test_security.py`](tests/unit/test_security.py):

```python
from app.core.security import generate_api_key, hash_api_key


def test_generate_api_key_has_prefix_and_is_unique() -> None:
    first = generate_api_key()
    second = generate_api_key()
    assert first.startswith("ne_")
    assert second.startswith("ne_")
    assert first != second


def test_hash_api_key_is_deterministic() -> None:
    raw = "ne_example-key"
    assert hash_api_key(raw) == hash_api_key(raw)


def test_hash_api_key_differs_for_different_inputs() -> None:
    assert hash_api_key("ne_a") != hash_api_key("ne_A")


def test_hash_api_key_is_not_the_raw_key() -> None:
    raw = generate_api_key()
    hashed = hash_api_key(raw)
    assert hashed != raw
    assert len(hashed) == 64
    int(hashed, 16)  # raises if not hex
```

- **Patrón:** one-way hash de credencial (no “encryption”: no se puede descifrar).
- **Por qué en este servicio:** si alguien copia la tabla `clients`, ve `e3b0c4…`, no `ne_abc…`. Ejemplo: el dump de un backup no sirve para pegar el header.
- **Alternativa descartada:** bcrypt (D3) y HMAC con `SECRET_KEY` (D4).
- **Capa:** `app/core/`. El dominio no sabe qué es una key. El modelo no hashea.

- **Commit (si EsrgaN autoriza):**

```text
feat: hash API keys with SHA-256 before they touch Postgres

Store only a deterministic digest so a leaked clients table
does not reveal the header value apps send.
```

---

### Paso 5.2 — `ClientRepository`

Crear [`app/repositories/client_repository.py`](app/repositories/client_repository.py). Responsabilidad única: buscar un cliente por hash. Quién lo llama: `get_current_client`. El router **no** lo llama.

```python
"""Data access for Client rows. Routers must not query Session themselves."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client import Client


class ClientRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_hashed_api_key(self, hashed_api_key: str) -> Client | None:
        """Return the client with this digest, or None if no row matches."""
        return self._session.scalar(
            select(Client).where(Client.hashed_api_key == hashed_api_key)
        )
```

Editar [`app/repositories/__init__.py`](app/repositories/__init__.py):

```python
"""Persistence adapters: repository implementations."""

from app.repositories.client_repository import ClientRepository

__all__ = ["ClientRepository"]
```

Crear [`tests/integration/test_client_repository.py`](tests/integration/test_client_repository.py) usando el `db_session` **con rollback** de Fase 4 (aquí no hay HTTP; la misma transacción ve el insert):

```python
from sqlalchemy.orm import Session

from app.core.security import generate_api_key, hash_api_key
from app.models import Client
from app.repositories import ClientRepository


def test_get_by_hashed_api_key_returns_row(db_session: Session) -> None:
    raw = generate_api_key()
    row = Client(name="checkout-app", hashed_api_key=hash_api_key(raw), is_active=True)
    db_session.add(row)
    db_session.flush()

    found = ClientRepository(db_session).get_by_hashed_api_key(hash_api_key(raw))
    assert found is not None
    assert found.id == row.id
    assert found.hashed_api_key != raw


def test_get_by_hashed_api_key_returns_none_for_unknown(db_session: Session) -> None:
    found = ClientRepository(db_session).get_by_hashed_api_key(hash_api_key("ne_nope"))
    assert found is None
```

- **Patrón:** repository (la consulta vive en persistencia, no en el router).
- **Por qué:** ejemplo: mañana el lookup añade `is_active` en SQL. Cambias **un** archivo, no tres endpoints.
- **Alternativa descartada:** `session.execute` dentro de `deps.py`. Funciona hoy; rompe la regla “routers/deps no son el sitio de las queries” y duplica SQL cuando exista `/send`.
- **Capa:** `app/repositories/`. Puede importar modelos. **No** puede importar FastAPI.

- **Commit (si EsrgaN autoriza):**

```text
feat: look up clients by hashed API key

Keep the SELECT in a repository so auth Depends never owns SQL.
```

---

### Paso 5.3 — Errors, `get_db`, `get_current_client`

Crear [`app/api/errors.py`](app/api/errors.py):

```python
"""HTTP-layer errors for the API composition root. Not domain exceptions."""


class UnauthorizedError(Exception):
    """Missing, invalid, or inactive API key. Handler always returns the same 401 body."""
```

Crear [`app/api/deps.py`](app/api/deps.py). Responsabilidad: composition root de FastAPI (sesión + cliente autenticado). Puede importar modelos y repositorios. Los **routers** no.

```python
"""FastAPI dependencies: DB session and current client from X-API-Key."""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.api.errors import UnauthorizedError
from app.core.config import get_settings
from app.core.security import hash_api_key
from app.repositories.client_repository import ClientRepository
from app.schemas.client import AuthenticatedClient

logger = logging.getLogger("app.auth")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    """Yield a short-lived session from the lifespan factory. Do not commit here."""
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_current_client(
    session: Annotated[Session, Depends(get_db)],
    api_key: Annotated[str | None, Depends(api_key_header)],
) -> AuthenticatedClient:
    """Resolve X-API-Key to an active client. Never return the ORM model to routers."""
    if not api_key:
        logger.info("api_key_rejected", extra={"reason": "missing"})
        raise UnauthorizedError()

    client = ClientRepository(session).get_by_hashed_api_key(hash_api_key(api_key))
    if client is None or not client.is_active:
        logger.info("api_key_rejected", extra={"reason": "unknown_or_inactive"})
        raise UnauthorizedError()

    logger.info("client_authenticated", extra={"client_id": str(client.id)})
    return AuthenticatedClient(id=client.id, name=client.name)
```

`get_settings` ya existe en `app.core.config`. **No** hace falta reenvolverlo salvo que un router lo inyecte: si lo exportas, reexporta el mismo callable (`from app.core.config import get_settings`). No dupliques el `lru_cache`.

Crear [`app/schemas/client.py`](app/schemas/client.py) **en este paso** porque `deps.py` lo importa (si prefieres, 5.3 y 5.4 se pueden aterrizar en el mismo commit; no dejes `deps.py` importando un módulo que no existe):

```python
"""Pydantic v2 schemas for authenticated client responses."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class AuthenticatedClient(BaseModel):
    """What HTTP handlers may see after X-API-Key succeeds. No hash, no secrets."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
```

Editar [`app/main.py`](app/main.py): registrar el handler **antes** de montar routers. Añadir imports `Request`, `JSONResponse`, `UnauthorizedError`. No montes todavía `/clients` si lo dejas para 5.4; **sí** registra el handler aquí para que el 401 exista en cuanto el Depends se use.

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.errors import UnauthorizedError


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(RequestIdMiddleware)

    @application.exception_handler(UnauthorizedError)
    async def handle_unauthorized(
        _request: Request, _exc: UnauthorizedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key", "code": "unauthorized"},
            headers={"WWW-Authenticate": "ApiKey"},
        )

    application.include_router(health_router)
    # include_router(clients) llega en el paso 5.4 si este commit se parte
    return application
```

Si 5.3 y 5.4 van juntos (recomendado si EsrgaN pide un commit por paso “que compile”), monta el router en el mismo diff.

Health y request-id siguen verdes: el handler nuevo no cambia `/health`.

- **Patrón:** dependency injection (FastAPI `Depends`) + composition root.
- **Por qué:** ejemplo: `/me` y más adelante `/send` piden el mismo `Depends(get_current_client)`. No copias el hash en cada endpoint.
- **Alternativa descartada:** middleware que mete `request.state.client`. Un middleware corre para **todas** las rutas (incluido health) o necesita allowlists. `Depends` es opt-in por endpoint.
- **Otra alternativa descartada:** `HTTPBearer` / JWT. `AGENTS.md` lo prohíbe; las apps no hacen login.
- **Capa:** `app/api/deps.py` (HTTP). `get_db` no vive en `app/core/db.py` porque leer `request.app.state` es cosa de FastAPI.

- **Commit (si EsrgaN autoriza):**

```text
feat: resolve X-API-Key through FastAPI Depends

Authenticate machine clients at the composition root so routers
never hash keys or open their own sessions.
```

---

### Paso 5.4 — `GET /api/v1/clients/me`

Crear [`app/api/routers/clients.py`](app/api/routers/clients.py). Responsabilidad única: exponer quién es el cliente autenticado. Thin router: parse (nada) → Depends → schema.

```python
"""Authenticated client probe. Product send routes arrive in a later phase."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_client
from app.schemas.client import AuthenticatedClient

router = APIRouter(prefix="/api/v1/clients", tags=["clients"])


@router.get("/me", response_model=AuthenticatedClient)
def read_me(
    current_client: Annotated[AuthenticatedClient, Depends(get_current_client)],
) -> AuthenticatedClient:
    """Return the active client bound to X-API-Key. 401 is handled in deps."""
    return current_client
```

Editar [`app/main.py`](app/main.py): `include_router` del clients router junto a health.

**Prohibido en el router:** `Session`, `select(Client)`, `hash_api_key`, `Client` ORM.

- **Patrón:** thin controller. El 401 no se decide aquí.
- **Por qué existe `/me` ahora:** sin esta ruta no hay forma honesta de probar 401/200 por HTTP hasta Fase 6. Ejemplo de curl en el README. No es un dashboard.
- **Alternativa descartada:** una ruta `__auth_probe` solo en tests. Enseñaría peor (EsrgaN no puede curl-earlo) y escondería el contrato OpenAPI.
- **Capa:** `app/api/routers/`. Prefijo `/api/v1/` obligatorio en producto. Health sigue sin versionar.

- **Commit (si EsrgaN autoriza):**

```text
feat: add GET /api/v1/clients/me behind X-API-Key

Give machine clients a versioned probe so auth is exercisable
before the send use case exists.
```

---

### Paso 5.5 — Tests HTTP (Postgres real, filas commiteadas)

El `db_session` de [`tests/integration/conftest.py`](tests/integration/conftest.py) hace rollback. `TestClient` abre **otro** engine en el lifespan. Si insertas con rollback, `/me` no ve la fila.

Añadir en [`tests/integration/conftest.py`](tests/integration/conftest.py) un fixture que **commitea** y borra al terminar (no sustituyas el de rollback: persistencia de Fase 4 lo necesita):

```python
import uuid
from collections.abc import Generator

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.models import Client


@pytest.fixture
def seeded_active_client(
    persistence_engine: Engine,
) -> Generator[tuple[uuid.UUID, str, str], None, None]:
    """Commit one active client so TestClient (separate pool) can authenticate."""
    raw = generate_api_key()
    name = f"auth-test-{uuid.uuid4().hex[:8]}"
    factory = create_session_factory(persistence_engine)
    with factory() as session:
        row = Client(name=name, hashed_api_key=hash_api_key(raw), is_active=True)
        session.add(row)
        session.commit()
        session.refresh(row)
        client_id = row.id
    yield client_id, raw, name
    with factory() as session:
        session.execute(delete(Client).where(Client.id == client_id))
        session.commit()
```

Crear [`tests/integration/test_auth.py`](tests/integration/test_auth.py) — **obligatorios**:

```python
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.models import Client

_UNAUTHORIZED = {
    "detail": "Invalid or missing API key",
    "code": "unauthorized",
}


def test_me_without_header_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/clients/me")
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED
    assert response.headers.get("www-authenticate") == "ApiKey"


def test_health_still_ok_without_api_key(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_me_with_unknown_key_returns_401(client: TestClient) -> None:
    response = client.get(
        "/api/v1/clients/me",
        headers={"X-API-Key": "ne_this-key-is-not-in-the-database"},
    )
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED


def test_me_with_valid_key_returns_client(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    client_id, raw, name = seeded_active_client
    response = client.get("/api/v1/clients/me", headers={"X-API-Key": raw})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(client_id)
    assert body["name"] == name
    assert "hashed_api_key" not in body


def test_me_with_inactive_client_returns_401(
    client: TestClient,
    persistence_engine: Engine,
) -> None:
    raw = generate_api_key()
    factory = create_session_factory(persistence_engine)
    with factory() as session:
        row = Client(
            name="inactive-app",
            hashed_api_key=hash_api_key(raw),
            is_active=False,
        )
        session.add(row)
        session.commit()
        client_id = row.id
    try:
        response = client.get("/api/v1/clients/me", headers={"X-API-Key": raw})
        assert response.status_code == 401
        assert response.json() == _UNAUTHORIZED
    finally:
        with factory() as session:
            session.delete(session.get(Client, client_id))
            session.commit()
```

El test inactivo puede extraerse a un fixture `seeded_inactive_client` si queda más limpio; no dejes el `Client` en la BD si el assert falla (`try/finally` o fixture).

**Prohibido:** `time.sleep`, Twilio, `create_all`, TestClient pegándole a `/send`, log assertions que exijan la key en claro.

- **Patrón:** test de integración HTTP + BD real.
- **Por qué commit y no rollback:** ejemplo: dos cajas (pool del test vs pool de la app) no comparten la transacción abierta. Si no haces `commit`, el portero mira una mesa vacía.
- **Alternativa descartada:** SQLite en memoria. El UNIQUE de `hashed_api_key` sí se parecería; el resto del proyecto no, y `AGENTS.md` lo prohíbe como camino feliz.
- **Capa:** `tests/integration/`. No mockear `Client` ni el repositorio.

- **Commit (si EsrgaN autoriza):**

```text
test: reject missing and invalid API keys with 401

Prove X-API-Key lookup against local Postgres, including inactive
clients, without opening the send path.
```

---

### Paso 5.6 — Docs de status + README

Editar [`docs/STATUS.md`](docs/STATUS.md) **solo al cerrar la implementación** (otro turno, o el final de este PLAN cuando el código exista):

- Marcar Fase 5 hecha: `security.py`, `deps.py`, `ClientRepository`, `GET /api/v1/clients/me`, 401.
- Decir qué **sigue**: Fase 6 = `POST /send` persist `PENDING` + **puerto de cola** (no Celery real) + `202`.
- “Qué no existe” sigue incluyendo send, Redis, Celery, Docker, mapper de dominio.
- No marcar Fase 6 como hecha.

Editar [`README.md`](README.md):

- Status: “Phase 5: `X-API-Key` works on `GET /api/v1/clients/me`; still no `/send`”.
- Cómo sembrar **un** cliente local (REPL o `python -c`, no un `scripts/` nuevo):

```python
from app.core.config import get_settings
from app.core.db import create_engine_from_url, create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.models import Client

raw = generate_api_key()
print(raw)  # save this; it is shown once
engine = create_engine_from_url(get_settings().database_url.get_secret_value())
with create_session_factory(engine)() as session:
    session.add(Client(name="local-dev", hashed_api_key=hash_api_key(raw), is_active=True))
    session.commit()
```

- Curl:

```bash
curl -i -H "X-API-Key: PASTE_RAW_KEY" http://127.0.0.1:8000/api/v1/clients/me
# 200 {"id":"...","name":"local-dev"}

curl -i http://127.0.0.1:8000/api/v1/clients/me
# 401 {"detail":"Invalid or missing API key","code":"unauthorized"}
```

- `/health` sigue sin header.
- Docker sigue “fase posterior”.

- **Commit (si EsrgaN autoriza):**

```text
docs: record API key auth in local runbook and status
```

---

## 4. Checklist de cierre

- [ ] `pytest -q` verde (33 anteriores + security + repository + auth HTTP)
- [ ] `ruff check app tests` limpio
- [ ] `app/domain/` sigue sin importar FastAPI/SQLAlchemy
- [ ] Routers de producto no importan `app.models` ni `Session`
- [ ] Cero `create_all`, cero migración nueva, cero `commit` en `get_db`
- [ ] `GET /health` sigue 200 sin `X-API-Key`
- [ ] Cero `POST /send`, cero Redis, cero Celery, cero JWT, cero Docker, cero `passlib`
- [ ] 3–6 learning points en español **simple** para EsrgaN (qué es una API key vs JWT, por qué hash y no texto claro, por qué SHA-256 y no bcrypt, qué es `Depends`, por qué `/health` no pide llave, por qué el test de auth hace `commit`)
- [ ] Commits hechos o mensajes esperando a EsrgaN

**Prohibido al terminar:** `POST /send`, Celery, Redis, `BackgroundTasks`, JWT, Compose, alta HTTP de clientes.

---

## 5. Qué sigue (no implementar)

Siguiente `PLAN.md` (otra reescritura): **Accept send** — persistir `PENDING` + **puerto de cola** (interfaz, no Celery) + `202 Accepted`. Auth de esta fase se reutiliza. Todavía no hay worker ni Mailtrap.
