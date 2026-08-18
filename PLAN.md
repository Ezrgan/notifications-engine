# PLAN.md — Fase 8: Token Bucket Redis (Homebrew) + HTTP 429

> **REGLA OBLIGATORIA PARA TODOS LOS AGENTES:**
> Antes de ejecutar cualquier paso, leer y acatar [`AGENTS.md`](./AGENTS.md), [`.cursor/rules/`](./.cursor/rules/) (sobre todo `fastapi.mdc`, `testing.mdc` y `anti-overengineering.mdc`) y [`docs/HOW_TO_WRITE_THE_NEXT_PLAN.md`](./docs/HOW_TO_WRITE_THE_NEXT_PLAN.md).
> Este archivo es el **único plan ejecutable**. Describe **una sola fase**. Cuando cierre, EsrgaN **reescribe** `PLAN.md` entero (ver el playbook en `docs/`).
> No implementar Celery, broker de cola en Redis, provider simulado, DLQ, retries, JWT, alta HTTP de clientes, Prometheus ni Docker.

> **Cómo está pensado este documento:**
> Un agente debe poder implementarlo **sin inventar**. Cada paso: archivos exactos, contrato, tests, commit propuesto, qué no tocar.
> Código completo. Cero placeholders. Cero `# ... rest of code ...`.
> Enseñar a EsrgaN en **español simple**, con ejemplos. Sin jerga sin definir.

> **Estado de partida (verificado):**
> Rama actual `feat/phase-7-metrics` = `5a3040d` (`docs: record GET /metrics in the local runbook`).
> `main` / `origin/main` = `7a2b828` — **aún no tiene** Fase 7. No partir de `main`.
> `pytest -q` → **76 passed**. `ruff check app tests` limpio.
> Hay `POST /send` → 202 + `PENDING`, `GET …/status`, `GET /metrics`, `X-API-Key`, cola **in-memory**.
> **No** existe `REDIS_URL` en Settings, paquete `redis`, Token Bucket, middleware 429, ni Redis en la máquina (`redis-cli` / `redis-server` no están). `.env.example` deja `REDIS_URL` comentado. `pyproject.toml` no lista `redis` ni `celery`.

---

## 0. Decisiones congeladas (esta fase)

| # | Decisión | Valor congelado |
| --- | --- | --- |
| D1 | Idea de la fase | El mostrador acepta como mucho **10 envíos por minuto por cliente**. El request 11 en esa ventana recibe **429** y **no** crea una fila `PENDING`. Nadie envía email. Nadie arranca Celery. |
| D2 | Algoritmo | **Token Bucket** (cubo de fichas). Cubo de capacidad 10. Cada request de `POST /send` gasta **1** ficha. Las fichas se rellenan de forma continua: 10 por 60 s (1 ficha cada 6 s). Un cliente quieto 1 minuto vuelve a tener 10. Eso **permite un ráfaga** de 10 seguidos (ejemplo: un checkout dispara 10 emails de “pedido confirmado” a la vez) y luego frena. |
| D3 | Por qué no ventana fija | Un `INCR` + `EXPIRE 60` (fixed window) en el segundo 59 deja mandar 10, y en el segundo 61 otros 10 → 20 en ~2 s. El cubo no tiene esa costura. Leaky Bucket se descarta: drena más suave, peor para un API que *quiere* ráfagas cortas. |
| D4 | Dónde vive el estado | **Redis Homebrew**, no un `dict` en Python. Ejemplo: dos procesos `uvicorn` (o mañana dos réplicas) deben ver **el mismo** cubo. Un dict en RAM le daría 10 fichas a cada proceso → 20 envíos. `slowapi` con storage en memoria está **prohibido**. |
| D5 | Atomicidad | Un script **Lua** ejecutado con `EVAL` (un round-trip). Prohibido GET tokens → restar en Python → SET: dos requests concurrentes leerían 1 ficha y ambos pasarían. Lua corre dentro de Redis; nadie se cuela en medio. |
| D6 | Cuánto | Default **10/minuto** vía Settings `rate_limit_per_minute` (no un literal `10` en el middleware). Periodo de recarga **60_000 ms**. La columna `clients.rate_limit_per_minute` **no se cablea** en esta fase: exige un SELECT extra en el limiter y cambiar `/me`. El default global *es* el contrato de v1; el override queda para un recorte futuro. Cero Alembic. |
| D7 | Qué rutas | **Solo** `POST /api/v1/notifications/send`. `/health`, `/me`, `/status`, `/metrics` **no** gastan fichas. Ejemplo: el checkout agota las 10 y aún puede preguntar `GET /status`. OPTIONS tampoco. |
| D8 | Clave del cubo | Si hay header `X-API-Key` → `rl:key:{sha256(key)}` usando `hash_api_key` (nunca la key en claro en Redis). Si **no** hay header → `rl:ip:{request.client.host}` (o `unknown` si no hay client). No confiar en `X-Forwarded-For` (no hay proxy en v1). Claves inválidas (header presente, no está en BD) **sí** usan el cubo del hash: un atacante que prueba keys a lo loco también se frena. |
| D9 | Orden HTTP | Middleware **antes** de auth y de validar el body. Ejemplo: 10 JSON basura + 1 body bueno → el bueno puede ser 429. Eso es correcto: el limiter protege el proceso, no “solo los requests bien formados”. Probe sin key con cubo IP vacío → **429**, no 401 (D10). Probe sin key con cubo lleno → sigue a auth → **401**. |
| D10 | 429 vs 401 | Cuerpo 429: `{"detail":"Rate limit exceeded","code":"rate_limited"}`. Header **`Retry-After`**: entero de segundos ≥ 1 (tiempo hasta 1 ficha nueva). 401 de auth **no cambia**. Si ambos podrían aplicar, gana el middleware (429). |
| D11 | Redis caído | No aceptar trabajo. **503** `{"detail":"Rate limiter unavailable","code":"service_unavailable"}`. **Cero** fila nueva. Prohibido un dict de fallback “porque Redis no responde”. Health **no** hace ping a Redis: `GET /health` sigue 200 aunque Redis esté muerto (es liveness del proceso, no readiness). |
| D12 | Settings | `redis_url: SecretStr` **obligatorio**, prefijo `redis://`. `rate_limit_per_minute: int` default 10, `ge=1`. Sin `REDIS_URL` el proceso **no arranca** (fail-fast, igual que `SECRET_KEY`). La URL de tests puede ser `redis://localhost:6379/0` aunque el test no se conecte (D15). |
| D13 | Cliente Redis | Paquete `redis` (sync), creado en **lifespan**, guardado en `app.state.redis`. `TokenBucket` en `app.state.token_bucket`. Endpoints **no** llaman `Redis.from_url`. Cerrar el cliente al apagar. Cola de notificaciones **sigue** `InMemoryNotificationQueue`. Redis **no** es broker en esta fase. |
| D14 | Capas | `TokenBucket` → `app/core/rate_limit.py` (infra, como `security.py`). Middleware HTTP → `app/api/middleware/rate_limit.py`. Routers de send **no** ganan SQL ni Redis. `NotificationService.accept` **no cambia**. Dominio **no** importa Redis. |
| D15 | Tests y FakeRedis | Unitarios del cubo: `fakeredis.FakeRedis` + reloj inyectado `now_ms` (**cero** `time.sleep`). HTTP: `ENVIRONMENT=test` → lifespan usa `FakeRedis`, no el daemon. Local/`uvicorn` (`environment=local`) usa Redis **real**. FakeRedis es un emulador del protocolo Redis (incluye Lua), **no** es el dict prohibido. Integración HTTP **no** exige `brew services start redis`. El runbook local **sí** lo exige para `uvicorn`. |
| D16 | Middleware sync | Routers siguen `def` (no `async def`). Redis sync dentro de `BaseHTTPMiddleware` (igual que hoy el resto). **No** añadir `redis.asyncio` en esta fase. A esta escala (miles/día) 1 ms bloqueando no es el problema; dos cubos en RAM sí lo es. |
| D17 | Replay / 422 | Un replay de `idempotency_key` **gasta** ficha (es otro HTTP). Un 422 **gasta** ficha (el middleware corre antes). El 11º replay en un minuto es 429. |
| D18 | Libs | `redis>=5.2,<6` en dependencies. `fakeredis>=2.26,<3` en **dev**. Prohibido `slowapi`, `fastapi-limiter`, `limits`, `celery`, `prometheus-client`. |
| D19 | Homebrew | `brew install redis` + `brew services start redis`. Pin de Compose **no**. Un solo Redis local, índice **0** (`redis://localhost:6379/0`). Celery (fase 9) usará otro índice; no lo implementes. |
| D20 | Fuera de esta fase | Celery, provider, DLQ, retries, mapper de `InvalidStatusTransition`, `ClientService`, JWT, Docker, cablear `Client.rate_limit_per_minute`, cambiar el puerto de cola a Redis. |
| D21 | Git | Rama `feat/phase-8-token-bucket` **desde** `feat/phase-7-metrics` (`5a3040d`). **No** desde `main` (`7a2b828`). Commits **solo si EsrgaN lo pide**. |
| D22 | Docker / extras | Prohibidos. No Kafka, JWT, Prisma, Compose, Celery. |

---

## 1. Diagnóstico (por qué esta fase)

Archivos reales, no memoria:

1. [`docs/STATUS.md`](docs/STATUS.md) marca Fases 1–7 hechas. [`AGENTS.md`](AGENTS.md) §10.1 siguiente número libre = **8 Rate limit**. No saltar a Celery (9): el worker no enseña “quién paga el cubo”, y `POST /send` hoy acepta sin freno.
2. [`app/core/config.py`](app/core/config.py) solo exige `SECRET_KEY` + `DATABASE_URL`. El docstring dice que `REDIS_URL` está ausente a propósito. [`.env.example`](.env.example) lo tiene comentado. [`pyproject.toml`](pyproject.toml) no lista `redis`.
3. [`app/api/middleware/`](app/api/middleware/) solo tiene `request_id.py`. [`app/main.py`](app/main.py) lifespan abre Postgres + cola in-memory; **cero** Redis. [`app/api/routers/notifications.py`](app/api/routers/notifications.py) llama `accept` sin mirar un presupuesto.
4. [`app/models/client.py`](app/models/client.py) ya tiene `rate_limit_per_minute` nullable (Fase 4). **No** lo uses ahora (D6): el limiter corre *antes* de auth y no debe hacer un SELECT para el default 10.
5. En esta máquina **no hay** `redis-server` / `redis-cli`. El paso 8.0 lo instala. Los tests HTTP no dependen de ese daemon (D15).
6. Ejemplo de uso: el checkout de la app A manda 10 `POST /send` → diez `202`. El 11º → `429` + `Retry-After: 6` (aprox. el tiempo de 1 ficha). La app B con otra API key sigue en `202`. `GET /health` nunca se entera.

---

## 2. Árbol al cerrar esta fase

```text
pyproject.toml                              # EDITAR: redis runtime + fakeredis dev
.env.example                                # EDITAR: REDIS_URL y RATE_LIMIT_PER_MINUTE
app/core/config.py                          # EDITAR: redis_url + rate_limit_per_minute
app/core/rate_limit.py                      # NUEVO: TokenBucket + Lua
app/api/errors.py                           # no tocar (401 sigue igual; 429/503 los arma el middleware)
app/api/middleware/__init__.py              # EDITAR: docstring
app/api/middleware/rate_limit.py            # NUEVO: RateLimitMiddleware
app/main.py                                 # EDITAR: lifespan Redis, middleware, handlers 429/503 limiter
tests/conftest.py                           # EDITAR: REDIS_URL en el env de pytest
tests/unit/test_config.py                   # EDITAR: fail-fast REDIS_URL + default 10
tests/unit/test_rate_limit.py               # NUEVO: cubo con fakeredis, reloj inyectado
tests/integration/test_rate_limit.py        # NUEVO: 429, aislamiento, health, 503, no-persist
README.md                                   # EDITAR: brew redis + curl 429
docs/STATUS.md                              # EDITAR en el último paso de implementación
```

**No crear:** `celery_app.py`, `tasks.py`, `app/providers/*` reales, `Dockerfile`, `docker-compose.yml`, revisión Alembic, tabla `rate_limits`, `BackgroundTasks`.

**No tocar:** máquina de estados, modelos/columnas, `GET /health` (sigue sin I/O), `hash_api_key` (solo **llamarlo**), `create_all`, `NotificationService.accept` / `get_status`, puerto de cola in-memory, routers de metrics/clients (el middleware filtra por path), `AuthenticatedClient` (no añadir `rate_limit_per_minute` a `/me`).

---

## 3. Git

Fase 7 **no** está en `main`. Crear la rama así:

```bash
git checkout feat/phase-7-metrics
# HEAD esperado: 5a3040d
git checkout -b feat/phase-8-token-bucket
```

**Nunca** partir de `main` ni de `feat/phase-6-accept-send`. **Nunca** commitear en `main`.

Antes de cerrar cada paso de código:

```bash
source .venv/bin/activate
pytest -q
ruff check app tests
```

Los 76 tests de Fases 2–7 deben seguir verdes (más los nuevos de esta fase).

---

## FASE 0 — Preparación

- [ ] `pytest -q` → 76 passed **antes** de editar
- [ ] `ruff check app tests` limpio
- [ ] Rama `feat/phase-8-token-bucket` creada desde `feat/phase-7-metrics` (`5a3040d`)
- [ ] Redis local (para `uvicorn`, no para pytest):

```bash
brew install redis
brew services start redis
redis-cli ping    # debe imprimir PONG
```

- [ ] Cero Docker, cero `celery`, cero `slowapi`
- [ ] Enseñar a EsrgaN (ejemplo): un **Token Bucket** es un tarro de 10 fichas de metro. Cada `POST /send` tira una ficha. Cada 6 segundos cae una ficha nueva, y el tarro nunca pasa de 10. Si el tarro está vacío, el torniquete no abre (429) y te dice cuántos segundos esperar (`Retry-After`). Un papelito en el cajón de *un* empleado (dict en RAM) no sirve si hay dos torniquetes; Redis es el tarro **compartido**.

---

## FASE 8 — Token Bucket + 429

### Paso 8.1 — Settings + dependencia `redis`

Editar [`pyproject.toml`](pyproject.toml). Añadir a `dependencies` (junto a psycopg, **no** en dev):

```toml
    "redis>=5.2,<6",
```

Añadir a `project.optional-dependencies.dev` (junto a pytest):

```toml
    "fakeredis>=2.26,<3",
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
RATE_LIMIT_PER_MINUTE=10
```

Quien ya tenga `.env` debe copiar `REDIS_URL` y `RATE_LIMIT_PER_MINUTE` a mano (no commitear `.env`).

Editar [`app/core/config.py`](app/core/config.py). El archivo queda así (completo):

```python
"""Application settings loaded from the environment.

`secret_key`, `database_url`, and `redis_url` are required so a misconfigured
process fails at boot instead of running with silent empty config.
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


@lru_cache
def get_settings() -> Settings:
    """Cached settings so every request does not re-read the environment."""
    return Settings()
```

Editar [`tests/conftest.py`](tests/conftest.py): después de `SECRET_KEY` / `DATABASE_URL`, **antes** de importar `app.main`:

```python
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "10")
```

`ENVIRONMENT` ya es `test` en ese archivo. No lo cambies.

Editar [`tests/unit/test_config.py`](tests/unit/test_config.py): los tests que construyen `Settings(_env_file=None)` deben setear `REDIS_URL` (si no, el fail-fast nuevo los rompe). Extrae una constante y un helper mínimo, o añade `monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")` en **cada** test existente que hoy solo setea `SECRET_KEY` / `DATABASE_URL`. Añade:

```python
_TEST_REDIS_URL = "redis://localhost:6379/0"


def test_missing_redis_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_redis_url_without_redis_prefix_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", "http://localhost:6379/0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_rate_limit_per_minute_defaults_to_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.rate_limit_per_minute == 10


def test_rate_limit_per_minute_below_one_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key")
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

`test_valid_secret_key_is_not_in_repr` debe setear `REDIS_URL` y **no** incluir el URL en un assert de secreto (no es tan sensible como `SECRET_KEY`; no hace falta `SecretStr` extra-assert). `redis_url` **sí** es `SecretStr` para no filtrarlo en logs de Settings.

- **Patrón:** fail-fast configuration (`pydantic-settings`). El proceso cojo no arranca.
- **Por qué ahora:** esta fase **abre** Redis. El playbook prohibía exigir `REDIS_URL` *antes*; ya no aplica.
- **Alternativa descartada:** default `redis://localhost:6379/0` dentro de `Field(default=...)`. Un laptop sin Redis arrancaría el API y el primer send moriría con un error opaco. Fallar al boot enseña “te falta el .env”.
- **Capa:** `app/core/`. No importa FastAPI.

- **Commit (si EsrgaN autoriza):**

```text
chore: require REDIS_URL and pin the redis client

Fail boot without a broker-less Redis URL so the token bucket
cannot start talking to a hidden localhost default.
```

---

### Paso 8.2 — `TokenBucket` atómico (Lua)

Crear [`app/core/rate_limit.py`](app/core/rate_limit.py). Responsabilidad: el cubo. Quién lo llama: el middleware. **No** HTTP, **no** FastAPI.

```python
"""Atomic Token Bucket stored in Redis.

Callers pass a already-hashed identity (API-key hash or IP). This module never
sees a raw API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_LUA_CONSUME = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local period_ms = tonumber(ARGV[3])
local take = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])

if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed < 0 then
  elapsed = 0
end

local refill = elapsed * (capacity / period_ms)
tokens = math.min(capacity, tokens + refill)
ts = now

local allowed = 0
local retry_after = 0

if tokens >= take then
  tokens = tokens - take
  allowed = 1
else
  allowed = 0
  local missing = take - tokens
  local rate = capacity / period_ms
  retry_after = math.ceil(missing / rate / 1000)
  if retry_after < 1 then
    retry_after = 1
  end
end

redis.call('HSET', key, 'tokens', tokens, 'ts', ts)
redis.call('PEXPIRE', key, period_ms * 2)
return {allowed, retry_after}
"""


@dataclass(frozen=True)
class TokenBucketResult:
    """Outcome of one consume attempt."""

    allowed: bool
    retry_after_seconds: int


class TokenBucket:
    """Consume tokens from a Redis hash using one EVAL (no GET/SET race)."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client
        self._consume = redis_client.register_script(_LUA_CONSUME)

    def consume(
        self,
        key: str,
        *,
        capacity: int,
        refill_period_ms: int = 60_000,
        now_ms: int | None = None,
    ) -> TokenBucketResult:
        """Take one token from ``key``. ``now_ms`` is injectable so tests never sleep."""
        if now_ms is None:
            now_ms = int(self._redis.time()[0] * 1000)
        allowed, retry_after = self._consume(
            keys=[key],
            args=[now_ms, capacity, refill_period_ms, 1],
        )
        return TokenBucketResult(
            allowed=bool(int(allowed)),
            retry_after_seconds=int(retry_after),
        )
```

`redis.Redis.time()` devuelve `(seconds, microseconds)`. En FakeRedis también existe. Si `now_ms` viene del caller (tests), **no** llames `time()`.

**Prohibido:** un `get` + `set` en Python. Un `INCR` con TTL de 60 s (eso no es Token Bucket). Guardar la API key en claro como Redis key.

Crear [`tests/unit/test_rate_limit.py`](tests/unit/test_rate_limit.py):

```python
from __future__ import annotations

import fakeredis

from app.core.rate_limit import TokenBucket

_T0 = 1_700_000_000_000


def _bucket() -> TokenBucket:
    return TokenBucket(fakeredis.FakeRedis(decode_responses=True))


def test_allows_burst_up_to_capacity() -> None:
    bucket = _bucket()
    for _ in range(10):
        result = bucket.consume("rl:key:a", capacity=10, now_ms=_T0)
        assert result.allowed is True
    denied = bucket.consume("rl:key:a", capacity=10, now_ms=_T0)
    assert denied.allowed is False
    assert denied.retry_after_seconds >= 1


def test_keys_are_isolated() -> None:
    bucket = _bucket()
    for _ in range(10):
        bucket.consume("rl:key:a", capacity=10, now_ms=_T0)
    other = bucket.consume("rl:key:b", capacity=10, now_ms=_T0)
    assert other.allowed is True


def test_refill_allows_one_token_after_six_seconds() -> None:
    bucket = _bucket()
    for _ in range(10):
        bucket.consume("rl:key:a", capacity=10, now_ms=_T0)
    still_empty = bucket.consume("rl:key:a", capacity=10, now_ms=_T0 + 1_000)
    assert still_empty.allowed is False
    refilled = bucket.consume("rl:key:a", capacity=10, now_ms=_T0 + 6_000)
    assert refilled.allowed is True


def test_full_minute_restores_capacity() -> None:
    bucket = _bucket()
    for _ in range(10):
        bucket.consume("rl:key:a", capacity=10, now_ms=_T0)
    for _ in range(10):
        result = bucket.consume("rl:key:a", capacity=10, now_ms=_T0 + 60_000)
        assert result.allowed is True
    denied = bucket.consume("rl:key:a", capacity=10, now_ms=_T0 + 60_000)
    assert denied.allowed is False
```

Cero `time.sleep`. Cero Redis daemon. Cero FastAPI.

- **Patrón:** algoritmo + adapter Redis (script atómico). El cubo es infra, no dominio de notificaciones.
- **Por qué Lua:** ejemplo: dos `POST /send` del mismo checkout al mismo milisegundo. Sin Lua, ambos leen “queda 1 ficha” y ambos pasan. Con Lua, Redis serializa: uno pasa, el otro 429.
- **Alternativa descartada:** librería `slowapi` / `fastapi-limiter`. Esconderían el algoritmo y, con el default in-memory, **mentirían** con dos workers. Aquí el ejercicio *es* el cubo.
- **Capa:** `app/core/`. Puede hablar Redis. **No** puede importar `app.api` ni `app.models`.

- **Commit (si EsrgaN autoriza):**

```text
feat: add an atomic Redis token bucket

Keep consume+refill in one Lua EVAL so two API workers cannot
both spend the last token.
```

---

### Paso 8.3 — Lifespan + middleware + HTTP 429

**No** edites [`app/api/errors.py`](app/api/errors.py). `BaseHTTPMiddleware` no entrega un `raise` al `exception_handler` de FastAPI de forma fiable (a menudo acaba en 500). El middleware **devuelve** el `JSONResponse` 429/503. Esas respuestas son HTTP, no reglas de dominio: no las pongas en `app/domain/exceptions.py`.

Crear [`app/api/middleware/rate_limit.py`](app/api/middleware/rate_limit.py). Responsabilidad: traducir un request HTTP en `bucket.consume` o en 429/503. Quién lo registra: `create_app`.

```python
"""Rate-limit POST /send before auth, validation, persist, or enqueue."""

from __future__ import annotations

import logging

from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.security import hash_api_key

logger = logging.getLogger("app.rate_limit")

_SEND_PATH = "/api/v1/notifications/send"


def _bucket_key(request: Request) -> tuple[str, str]:
    """Return (redis_key, kind). kind is 'key' or 'ip' for logs; never the raw API key."""
    raw = request.headers.get("X-API-Key", "").strip()
    if raw:
        return f"rl:key:{hash_api_key(raw)}", "key"
    host = request.client.host if request.client is not None else "unknown"
    return f"rl:ip:{host}", "ip"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Spend one token on POST /send. Other routes pass through."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method != "POST" or request.url.path != _SEND_PATH:
            return await call_next(request)

        settings = get_settings()
        redis_key, kind = _bucket_key(request)
        bucket = request.app.state.token_bucket
        try:
            result = bucket.consume(
                redis_key,
                capacity=settings.rate_limit_per_minute,
            )
        except RedisError:
            logger.exception(
                "rate_limit_store_unavailable",
                extra={"kind": kind},
            )
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Rate limiter unavailable",
                    "code": "service_unavailable",
                },
            )

        if not result.allowed:
            logger.info(
                "rate_limit_exceeded",
                extra={"kind": kind, "retry_after": result.retry_after_seconds},
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "code": "rate_limited"},
                headers={"Retry-After": str(result.retry_after_seconds)},
            )

        logger.info("rate_limit_allowed", extra={"kind": kind})
        return await call_next(request)
```

Editar [`app/api/middleware/__init__.py`](app/api/middleware/__init__.py):

```python
"""HTTP middleware: request id and POST /send Token Bucket."""
```

Editar [`app/main.py`](app/main.py). Cambios concretos (no reescribas a ciegas: el archivo actual ya tiene handlers 401/404/503 de cola).

Imports nuevos:

```python
from redis import Redis

from app.api.middleware.rate_limit import RateLimitMiddleware
from app.core.rate_limit import TokenBucket
```

El import de `UnauthorizedError` **sigue** como está hoy (`from app.api.errors import UnauthorizedError`). **No** importes `fakeredis` arriba del archivo.

Dentro de `lifespan`, **después** de asignar `notification_queue` y **antes** del `yield`:

```python
    if settings.environment == "test":
        from fakeredis import FakeRedis

        redis_client: Redis | FakeRedis = FakeRedis(decode_responses=True)
    else:
        redis_client = Redis.from_url(
            settings.redis_url.get_secret_value(),
            decode_responses=True,
        )
    application.state.redis = redis_client
    application.state.token_bucket = TokenBucket(redis_client)
```

En el shutdown, **antes** de `engine.dispose()`:

```python
    application.state.redis.close()
```

`FakeRedis.close()` existe. No hagas ping aquí.

En `create_app`, **añade el rate-limit primero** y el request-id **después** (Starlette: el último `add_middleware` es el más externo). Así `X-Request-ID` también sale en un 429:

```python
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(RequestIdMiddleware)
```

**No** añadas handlers 429/503 en `create_app`: el middleware ya responde. El handler de `QueueUnavailableError` **no se borra**.

Crear [`tests/integration/test_rate_limit.py`](tests/integration/test_rate_limit.py) — **obligatorios**:

```python
import uuid

from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy import Engine, delete, func, select

from app.core.db import create_session_factory
from app.core.security import generate_api_key, hash_api_key
from app.main import create_app
from app.models import Client, Notification

_MINIMAL_BODY = {
    "channel": "email",
    "recipient": "user@example.com",
    "template": "welcome",
}
_RATE_LIMITED = {
    "detail": "Rate limit exceeded",
    "code": "rate_limited",
}
_LIMITER_UNAVAILABLE = {
    "detail": "Rate limiter unavailable",
    "code": "service_unavailable",
}


def test_eleventh_send_returns_429(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    headers = {"X-API-Key": raw}
    responses = [
        client.post("/api/v1/notifications/send", headers=headers, json=_MINIMAL_BODY)
        for _ in range(11)
    ]
    assert [r.status_code for r in responses[:10]] == [202] * 10
    last = responses[10]
    assert last.status_code == 429
    assert last.json() == _RATE_LIMITED
    assert int(last.headers["retry-after"]) >= 1


def test_429_does_not_insert_an_eleventh_row(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    client_id, raw, _ = seeded_active_client
    headers = {"X-API-Key": raw}
    for _ in range(11):
        client.post("/api/v1/notifications/send", headers=headers, json=_MINIMAL_BODY)
    factory = create_session_factory(persistence_engine)
    with factory() as session:
        count = session.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.client_id == client_id
            )
        )
    assert count == 10


def test_second_api_key_is_not_blocked_by_first_bucket(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    _, raw_a, _ = seeded_active_client
    headers_a = {"X-API-Key": raw_a}
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/notifications/send", headers=headers_a, json=_MINIMAL_BODY
            ).status_code
            == 202
        )

    raw_b = generate_api_key()
    factory = create_session_factory(persistence_engine)
    with factory() as session:
        other = Client(
            name="other-limited-app",
            hashed_api_key=hash_api_key(raw_b),
            is_active=True,
        )
        session.add(other)
        session.commit()
        other_id = other.id
    try:
        ok = client.post(
            "/api/v1/notifications/send",
            headers={"X-API-Key": raw_b},
            json=_MINIMAL_BODY,
        )
        assert ok.status_code == 202
    finally:
        with factory() as session:
            session.execute(delete(Notification).where(Notification.client_id == other_id))
            session.delete(session.get(Client, other_id))
            session.commit()


def test_unauthenticated_probe_is_429_after_ip_bucket_exhausts(client: TestClient) -> None:
    responses = [
        client.post("/api/v1/notifications/send", json=_MINIMAL_BODY) for _ in range(11)
    ]
    assert responses[0].status_code == 401
    assert responses[10].status_code == 429
    assert responses[10].json() == _RATE_LIMITED


def test_health_and_metrics_are_not_rate_limited(
    client: TestClient,
    seeded_active_client: tuple[uuid.UUID, str, str],
) -> None:
    _, raw, _ = seeded_active_client
    headers = {"X-API-Key": raw}
    for _ in range(10):
        client.post("/api/v1/notifications/send", headers=headers, json=_MINIMAL_BODY)
    assert client.get("/health").status_code == 200
    metrics = client.get("/api/v1/metrics", headers=headers)
    assert metrics.status_code == 200
    assert metrics.json() == {"sent": 0, "failed": 0}


def test_send_returns_503_when_redis_raises(
    seeded_active_client: tuple[uuid.UUID, str, str],
    persistence_engine: Engine,
) -> None:
    class BoomBucket:
        def consume(self, *args: object, **kwargs: object) -> None:
            raise RedisError("down")

    _, raw, _ = seeded_active_client
    with TestClient(create_app()) as test_client:
        test_client.app.state.token_bucket = BoomBucket()
        response = test_client.post(
            "/api/v1/notifications/send",
            headers={"X-API-Key": raw},
            json=_MINIMAL_BODY,
        )
        assert response.status_code == 503
        assert response.json() == _LIMITER_UNAVAILABLE
        factory = create_session_factory(persistence_engine)
        with factory() as session:
            count = session.scalar(
                select(func.count()).select_from(Notification).where(
                    Notification.client_id == seeded_active_client[0]
                )
            )
        assert count == 0
```

`seeded_active_client` ya borra las `Notification` del owner en el teardown. El test de aislamiento limpia al **otro** cliente. Cero `time.sleep`. Cero Twilio. **No** mockees `NotificationService` en estos tests.

Los tests viejos de `POST /send` (1–2 llamadas) siguen 202: FakeRedis nace vacío por app y el fixture `client` crea una app nueva por test.

- **Patrón:** middleware HTTP (cross-cutting) + composition root (lifespan) + test de integración.
- **Por qué middleware y no `Depends` en el router:** ejemplo: un probe **sin** API key debe poder recibir 429 (D9–D10). `get_current_client` hoy lanza 401 y ni siquiera llegaría al limiter si este dependiera de un cliente autenticado. El middleware corre **antes**.
- **Alternativa descartada:** limiter solo en `NotificationService.accept`. El servicio no debe conocer Redis ni HTTP 429; y un 422 ni siquiera entra al servicio, así que el atacante de JSON basura no gastaría ficha.
- **Capa:** `app/api/middleware/` + `app/main.py`. El router de send **no se edita**.

- **Commit (si EsrgaN autoriza):**

```text
feat: reject exhausted POST /send with HTTP 429

Spend a Redis token before persist so a noisy client cannot
fill Postgres with PENDING rows.
```

---

### Paso 8.4 — Docs de status + README

Editar [`docs/STATUS.md`](docs/STATUS.md) **solo al cerrar la implementación** (otro turno, o el final de este PLAN cuando el código exista):

- Marcar Fase 8 hecha: Redis Homebrew, `REDIS_URL` obligatorio, Token Bucket Lua, middleware en `POST /send`, 429 + `Retry-After`, 503 si Redis cae, tests con fakeredis.
- Decir qué **sigue**: Fase 9 = Celery worker **en el mismo venv** + provider **simulado**. Redis ya existe; el broker usará **otro índice** (`/1`), no un segundo servidor.
- “Qué no existe” **deja de listar** Redis / Token Bucket / 429. Sigue incluyendo Celery, providers, DLQ, Docker, mapper de `InvalidStatusTransition`.
- No marcar Fase 9 como hecha.

Editar [`README.md`](README.md):

- Status: “Phase 8: Token Bucket in local Redis; `POST /send` returns 429 after 10 req/min per API key; still no Celery”.
- Prerequisites: Redis 7.x (o el formula de Homebrew) vía `brew install redis`.
- Setup: `brew services start redis` + `redis-cli ping`.
- `.env`: `REDIS_URL=redis://localhost:6379/0` y `RATE_LIMIT_PER_MINUTE=10`.
- Curl después del de send:

```bash
# 11th send in the same minute (same API key):
curl -i -H "X-API-Key: PASTE_RAW_KEY" -H "Content-Type: application/json" \
  -d '{"channel":"email","recipient":"user@example.com","template":"welcome"}' \
  http://127.0.0.1:8000/api/v1/notifications/send
# 429 {"detail":"Rate limit exceeded","code":"rate_limited"}
# Retry-After: 6
```

- Dejar claro: `/health` no habla con Redis. Docker sigue “fase posterior”. Celery no está.

- **Commit (si EsrgaN autoriza):**

```text
docs: record Homebrew Redis and 429 in the local runbook
```

---

## 4. Checklist de cierre

- [ ] `pytest -q` verde (76 anteriores + config REDIS_URL + cubo unitario + 429 HTTP)
- [ ] `ruff check app tests` limpio
- [ ] `app/domain/` sigue sin importar FastAPI/SQLAlchemy/Redis/Pydantic
- [ ] Router de send **no** importa Redis; `NotificationService.accept` intacto
- [ ] Cero `create_all`, cero migración nueva, cero `commit` en `get_db`
- [ ] `POST /send` 1–10 → 202; 11 → 429 `{detail, code: rate_limited}` + `Retry-After`
- [ ] 429 **no** inserta la 11ª fila
- [ ] Otra API key no comparte el cubo
- [ ] Sin `X-API-Key`, el 11º probe al send es 429 (cubo IP), no un 401 eterno
- [ ] `GET /health` sigue 200 sin API key y **sin** I/O a Redis
- [ ] `GET /metrics` y `GET /status` no gastan fichas
- [ ] Redis caído en send → 503 limiter, cero persist
- [ ] Cero `time.sleep`, cero dict-limiter, cero `slowapi`, cero Celery, cero JWT, cero Docker
- [ ] `uvicorn` local documentado con `brew services start redis`
- [ ] 3–6 learning points en español **simple** para EsrgaN (qué es el cubo, por qué Redis y no RAM, por qué Lua, por qué 429 antes de persistir, por qué IP si no hay key, por qué FakeRedis en tests no es trampa)
- [ ] Commits hechos o mensajes esperando a EsrgaN

**Prohibido al terminar:** worker Celery, `import twilio`, Compose, mapper de transiciones, usar Redis como cola, cablear `rate_limit_per_minute` del modelo Client.

---

## 5. Qué sigue (no implementar)

Siguiente `PLAN.md` (otra reescritura): **Worker Celery en el mismo venv** + adapter de canal **simulado**. Redis ya está para el cubo; el broker será el mismo proceso Redis, **otro DB index**. FastAPI sigue sin enviar el email. No implementar Celery, providers ni Docker en este turno.
