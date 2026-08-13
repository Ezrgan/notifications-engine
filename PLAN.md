# PLAN.md — Fase 3: Dominio (canales, estados, transiciones, excepciones)

> **REGLA OBLIGATORIA PARA TODOS LOS AGENTES:**
> Antes de ejecutar cualquier paso, leer y acatar [`AGENTS.md`](./AGENTS.md), [`.cursor/rules/`](./.cursor/rules/) y [`docs/HOW_TO_WRITE_THE_NEXT_PLAN.md`](./docs/HOW_TO_WRITE_THE_NEXT_PLAN.md).
> Este archivo es el **único plan ejecutable**. Describe **una sola fase**. Cuando cierre, EsrgaN **reescribe** `PLAN.md` entero (ver el playbook en `docs/`).
> No implementar SQLAlchemy, Alembic, Celery, Redis, Token Bucket, `POST /send`, handlers HTTP de errores, métricas ni Docker.

> **Cómo está pensado este documento:**
> Un agente debe poder implementarlo **sin inventar**. Cada paso: archivos exactos, contrato, tests, commit propuesto, qué no tocar.
> Código completo. Cero placeholders. Cero `# ... rest of code ...`.
> Enseñar a EsrgaN en **español simple**, con ejemplos. Sin jerga sin definir.

> **Estado de partida (verificado en `feat/phase-2-settings-logging`, commit `e4f8589`):**
> Fase 2 **cerrada y verde**. `pytest -q` → 11 passed. `SECRET_KEY` obligatorio (`SecretStr`, min 16). Logging stdlib + `X-Request-ID`. `GET /health` → 200 `{"status":"ok"}`. `app/domain/` solo tiene `__init__.py` vacío de lógica. Cero modelos ORM. Cero Dockerfile.

---

## 0. Decisiones congeladas (esta fase)

| # | Decisión | Valor congelado |
| --- | --- | --- |
| D1 | Capa | Solo `app/domain/`. **Cero** imports de FastAPI, Pydantic, SQLAlchemy, Redis, Celery. Stdlib only (`enum`, excepciones). |
| D2 | `Channel` | `enum.StrEnum`: `EMAIL = "email"`, `SMS = "sms"`, `PUSH = "push"`, `WEBHOOK = "webhook"`. Esos cuatro. No `whatsapp`, no `slack`. |
| D3 | `NotificationStatus` | `enum.StrEnum`: `PENDING`, `PROCESSING`, `SENT`, `FAILED`. Valores string exactamente `"PENDING"`, `"PROCESSING"`, `"SENT"`, `"FAILED"` (mayúsculas, para que coincidan con el contrato de `GET /status` más adelante). |
| D4 | Transiciones **legales** | `PENDING → PROCESSING`. `PROCESSING → SENT`. `PROCESSING → FAILED`. `PROCESSING → PENDING` (reintento: vuelve a cola). |
| D5 | Estados **terminales** | `SENT` y `FAILED` no salen a ningún sitio. `SENT → PENDING`, `FAILED → SENT`, `FAILED → PROCESSING`, etc. son ilegales. |
| D6 | Atajos ilegales | `PENDING → SENT` y `PENDING → FAILED` son ilegales. Hay que pasar por `PROCESSING`. |
| D7 | API de la máquina | Tres funciones en `state_machine.py`: `can_transition(src, dst) -> bool`, `assert_transition(src, dst) -> None` (explota si ilegal), `transition(src, dst) -> NotificationStatus` (devuelve `dst` si legal). No una clase gigante. No un grafo genérico configurable. |
| D8 | Excepciones | Base `DomainError(Exception)`. Hija `InvalidStatusTransition(DomainError)` con atributos `from_status` y `to_status`. **No** mapear a HTTP en esta fase (no hay rutas de producto). **No** crear 15 clases “por si acaso”. |
| D9 | Qué **no** entra | Validar formato de email/teléfono. `retry_count`. Idempotencia. Cola. Persistencia. Schemas Pydantic de `/send`. |
| D10 | Tests | `tests/unit/domain/`. Sin `TestClient`. Sin `SECRET_KEY` extra (estos tests no importan `app.main`). |
| D11 | Git | Rama `feat/phase-3-domain` desde `feat/phase-2-settings-logging` (HEAD actual). Commits **solo si EsrgaN lo pide**. |
| D12 | Docker / deps nuevas | Prohibidos. `pyproject.toml` no se toca. |
| D13 | Docs de producto | No reescribir `README.md` salvo una línea de “Phase 3 status” **al final** del último paso. `docs/STATUS.md` se actualiza en el último paso. |

---

## 1. Diagnóstico (por qué esta fase)

1. Health y settings ya arrancan. El **negocio** (qué estados existen, cuáles se pueden cambiar) todavía no está en código. Si saltamos a Postgres, el status sería un string libre en la columna y `SENT → PENDING` se podría guardar sin que nadie proteste.
2. El dominio **antes** de la BD es a propósito: las reglas se testean sin Postgres. La tabla, más adelante, solo guarda lo que el dominio ya permite.
3. Excepciones propias: un `ValueError("bad")` no dice si falló el estado, la key o el JSON. `InvalidStatusTransition` sí.

---

## 2. Árbol al cerrar esta fase

```text
app/domain/
  __init__.py              # EDITAR: reexportar Channel, NotificationStatus, DomainError, InvalidStatusTransition, can_transition, assert_transition, transition
  enums.py                 # NUEVO
  exceptions.py            # NUEVO
  state_machine.py         # NUEVO
tests/unit/domain/
  __init__.py              # NUEVO (vacío o docstring de una línea)
  test_enums.py            # NUEVO (corto)
  test_state_machine.py    # NUEVO (el gordo)
docs/STATUS.md             # EDITAR en el último paso
README.md                  # EDITAR una línea de status
```

No crear `app/domain/entities.py`, ni `retry_policy.py`, ni handlers en `app/main.py`.

---

## 3. Git

```bash
git checkout feat/phase-2-settings-logging
git checkout -b feat/phase-3-domain
```

Antes de cerrar cada paso de código:

```bash
source .venv/bin/activate
pytest -q
ruff check app tests
```

Los 11 tests de la Fase 2 deben seguir verdes.

---

## FASE 0 — Preparación

- [ ] `pytest -q` → 11 passed (o más, todos verdes)
- [ ] `ruff check app tests` limpio
- [ ] No existe `app/domain/enums.py` todavía
- [ ] Rama `feat/phase-3-domain` creada
- [ ] Cero Docker, cero `pip install` nuevo

---

## FASE 3 — Dominio

### Paso 3.1 — Enums

Crear [`app/domain/enums.py`](app/domain/enums.py).

Usar `class Channel(StrEnum)` y `class NotificationStatus(StrEnum)` de `enum` (stdlib, Python 3.12). **No** `enum.Enum` con `.value` raro: `StrEnum` se compara y se serializa como string.

Contrato:

```python
Channel.EMAIL == "email"          # True
NotificationStatus.PENDING == "PENDING"  # True
list(Channel)                     # cuatro miembros
```

No añadir métodos de negocio en el enum (eso va en `state_machine.py`).

Tests [`tests/unit/domain/test_enums.py`](tests/unit/domain/test_enums.py):

- Hay exactamente esos cuatro channels y esos cuatro statuses.
- `Channel.EMAIL == "email"`.
- `NotificationStatus.SENT == "SENT"`.

- **Commit (si EsrgaN autoriza):**

```text
feat: add channel and notification status enums

Give the engine a closed set of channels and statuses before
any database column exists to store them.
```

---

### Paso 3.2 — Excepciones

Crear [`app/domain/exceptions.py`](app/domain/exceptions.py).

```python
class DomainError(Exception):
    """Base for business-rule failures. HTTP mapping comes in a later phase."""


class InvalidStatusTransition(DomainError):
    def __init__(self, from_status: NotificationStatus, to_status: NotificationStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Cannot transition from {from_status} to {to_status}"
        )
```

Importar los enums desde `app.domain.enums`, no al revés.

No crear `NotFoundError` ni `UnauthorizedError` ahora: no hay repositorio ni auth de producto.

Un test corto en `test_state_machine.py` (paso 3.3) basta para la excepción; no hace falta un archivo de tests solo para la clase vacía. Si el agente quiere `tests/unit/domain/test_exceptions.py` con un test de atributos `from_status`/`to_status`, está permitido (un test, no una suite).

- **Commit (si EsrgaN autoriza):**

```text
feat: add domain errors for illegal notification transitions

Raise a named error instead of a generic ValueError so later
HTTP mapping can tell business rules from bugs.
```

---

### Paso 3.3 — Máquina de estados

Crear [`app/domain/state_machine.py`](app/domain/state_machine.py).

Tabla congelada (no “config file”, un `frozenset` o dict módulo-level está bien):

```text
PENDING     -> {PROCESSING}
PROCESSING  -> {SENT, FAILED, PENDING}
SENT        -> {}
FAILED      -> {}
```

Funciones públicas exactas:

- `can_transition(src: NotificationStatus, dst: NotificationStatus) -> bool`
- `assert_transition(src: NotificationStatus, dst: NotificationStatus) -> None`  
  Si ilegal: `raise InvalidStatusTransition(src, dst)`. Si legal: no return útil.
- `transition(src: NotificationStatus, dst: NotificationStatus) -> NotificationStatus`  
  Llama a `assert_transition` y `return dst`. No muta ningún objeto (aún no hay entidad). Es una función pura.

Misma transición (`PENDING → PENDING`) es **ilegal** salvo que esté en la tabla (no está).

Tests [`tests/unit/domain/test_state_machine.py`](tests/unit/domain/test_state_machine.py) — **obligatorios**:

1. Cada transición legal de D4: `can_transition` True y `transition` devuelve `dst`.
2. `SENT → PENDING` → `InvalidStatusTransition` con `.from_status` y `.to_status` correctos.
3. `FAILED → SENT` → misma excepción.
4. `PENDING → SENT` → ilegal.
5. `PENDING → FAILED` → ilegal.
6. `SENT → SENT` → ilegal.
7. Un test parametrizado (pytest `parametrize`) que recorra todas las parejas ilegales **o** al menos las de esta lista; no hace falta generar 4×4 si las 6 de arriba están. Preferir `parametrize` en las legales (4 casos) + las ilegales nombradas.

Cero `TestClient`. Cero mocks.

Editar [`app/domain/__init__.py`](app/domain/__init__.py): reexportar los nombres públicos (D1 del árbol). `__all__` explícito.

- **Commit (si EsrgaN autoriza):**

```text
feat: encode legal notification status transitions

Reject SENT→PENDING in the domain so a later ORM column cannot
silently rewind a sent notification.
```

---

### Paso 3.4 — Docs de status + README

Editar [`docs/STATUS.md`](docs/STATUS.md): marcar Fase 3 hecha, listar `enums` / `state_machine` / excepciones, decir qué **sigue** (Postgres + Alembic, no send todavía).

Editar [`README.md`](README.md): una línea “Phase 3 status: domain states exist; still no `/send`”.

No copiar la máquina de estados al README (eso es `docs/STATUS.md`).

- **Commit (si EsrgaN autoriza):**

```text
docs: record domain status machine in the project status note
```

---

## 4. Checklist de cierre

- [ ] `pytest -q` verde (Fase 2 + tests de dominio)
- [ ] `ruff check app tests` limpio
- [ ] `app/domain/` no importa FastAPI/Pydantic/SQLAlchemy
- [ ] Solo las transiciones de D4 son legales
- [ ] `InvalidStatusTransition` se lanza en las ilegales
- [ ] Cero routers nuevos, cero Alembic, cero Celery
- [ ] 3–6 learning points en español **simple** para EsrgaN (qué es un enum, por qué el dominio no habla HTTP, ejemplo SENT→PENDING)
- [ ] Commits hechos o mensajes esperando a EsrgaN

**Prohibido al terminar:** `alembic init`, modelos SQLAlchemy, `POST /send`, mapper HTTP de excepciones, Redis.

---

## 5. Qué sigue (no implementar)

Siguiente `PLAN.md` (otra reescritura): **Postgres local + SQLAlchemy 2 Mapped + Alembic**. Las columnas `channel` y `status` usarán estos enums. No hay cola todavía.
