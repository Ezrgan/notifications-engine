# Cómo escribir el siguiente PLAN.md

Este documento es para **cualquier agente** (no solo el que hizo las fases 1–2). Si `PLAN.md` está cerrado y EsrgaN pide la siguiente fase, **reescribes `PLAN.md` entero**. No añades “Fase 4” debajo. No implementas la fase en el mismo turno salvo que EsrgaN lo pida aparte.

## 0. Leer antes de escribir (en este orden)

1. [`AGENTS.md`](../AGENTS.md) — ley. Si choca con tu idea, gana `AGENTS.md`.
2. [`docs/STATUS.md`](STATUS.md) — qué hay **de verdad** en el repo (no lo que recuerdes).
3. El árbol real (`app/`, `tests/`). Abre los archivos; no asumas el PLAN viejo.
4. `.cursor/rules/project.mdc` + la rule del área (fastapi, postgresql, celery, testing).
5. `git log --oneline -10` y `pytest -q` para el “estado de partida”.

Si STATUS y el código no coinciden, **arregla STATUS** o di la diferencia en el diagnóstico del nuevo PLAN. No inventes archivos.

## 1. Una fase = una idea

Escala del producto: **un** servicio, miles de notifs/día, 5–20 clientes. Si tu fase necesita Kafka, un segundo broker, JWT, dashboard, K8s o una lib “de senior” que `AGENTS.md` no nombra, **para y pregunta**. Eso es over-engineering aquí.

Lista larga de `AGENTS.md` §10.1 (brújula, **no** tareas):

| # | Fase | Idea única | Fuera de esa fase |
| --- | --- | --- | --- |
| 1 | Skeleton | venv + `/health` | todo lo demás |
| 2 | Settings + logs | `SECRET_KEY` + request id | dominio, DB |
| 3 | Dominio | enums + transiciones + excepciones | HTTP mapper, ORM |
| 4 | Persistencia | SQLAlchemy 2 + Alembic + Postgres **local** | send, Redis |
| 5 | API keys | hash + `X-API-Key` Depends | JWT |
| 6 | Accept send | persist `PENDING` + **puerto de cola** + 202 | Celery real, Mailtrap |
| 7 | Metrics | conteos por cliente | Prometheus/Grafana |
| 8 | Rate limit | Token Bucket Redis **Homebrew** + 429 | limiter in-memory |
| 9 | Worker | Celery en el **mismo venv** + provider simulado | imagen Docker |
| 10 | Retry + DLQ | 5s/15s/45s, FAILED + `notifications.dlq` | replay admin UI |
| 11 | README curl | runbook local | Compose |
| 12 | Docker | un `compose up` | no reescribir la app |

La siguiente fase es **el primer número de esa tabla que `docs/STATUS.md` marque como no hecho**. No dejes un número congelado en este párrafo (se queda viejo). No saltes fases “porque se ve más”.

## 2. Forma obligatoria del PLAN.md (copiar estructura)

El modelo de densidad es el de CatalogoVentas: pasos con archivos, contratos y checkboxes. El de **este** repo además:

1. Título: `PLAN.md — Fase N: <idea en una línea>`.
2. Bloque “regla obligatoria” + “una sola fase” + “anti-pereza”.
3. **Estado de partida verificado:** rama, commit corto, `pytest -q` N passed, una frase de qué hay. Si no corriste pytest, no mientas el número.
4. **§0 Decisiones congeladas** tabla D1…Dn. El agente implementador **no reinterpreta**.
5. **§1 Diagnóstico** sobre código real (ruta de archivo). Por qué **esta** fase ahora.
6. **§2 Árbol objetivo** de **esta** fase. Lista NUEVO / EDITAR / no tocar. Si no está en la lista, **no se crea**.
7. **§3 Git:** nombre de rama `feat/phase-N-<slug>`, commits solo si EsrgaN pide, un commit por paso, mensajes en inglés ya escritos.
8. **Fase 0** preparación: tests verdes **antes** de tocar.
9. Pasos  N.1, N.2… con contrato de código (firmas, status HTTP, enums). Tests nombrados. “Commit (si EsrgaN autoriza):” + mensaje.
10. **Checklist de cierre.** Incluir: no Docker si no es fase 12; teaching 3–6 puntos en español **simple** (EsrgaN lo pidió: ejemplos, no filosofía).
11. **§ Qué sigue:** una frase. “No implementar”.

Idioma del PLAN: español (EsrgaN lo lee). Código de ejemplo y commits: inglés.

## 3. Reglas para no inflar

- **No** Docker hasta la fase 12. Celery es un paquete Python, no una imagen.
- **No** exigir `DATABASE_URL` / `REDIS_URL` en Settings hasta que esa fase **abra** la conexión. Health no debe depender de Postgres.
- **No** `BackgroundTasks` de FastAPI para el envío. **No** JWT.
- **No** Prisma, Supabase, `src/`, segundo árbol.
- **No** 15 clases de excepción. Las justas para las reglas de **esa** fase.
- **No** instalar libs si stdlib o lo que ya está en `pyproject.toml` alcanza (logging Fase 2 = stdlib a propósito).
- Dominio **sin** FastAPI. Routers **sin** SQLAlchemy. Worker **sin** importar routers.
- Tests: mockear proveedores externos, no el dominio. Cero `time.sleep`. Cero Twilio real.
- Un concern por paso. Si un paso necesita Redis **y** el modelo ORM, son dos fases.

## 4. Git y enseñanza (no negociable)

- Commit / push / PR **solo** con pedido explícito de EsrgaN.
- Nunca commitear `.env`, `.venv`, `*.egg-info`.
- Explicar a EsrgaN en español claro: qué es, por qué, **ejemplo de uso**. Si una frase no tiene ejemplo, reescríbela.
- Al cerrar implementación: 3–6 learning points. Actualizar `docs/STATUS.md`.

## 5. Después de implementar (otro turno)

Cuando EsrgaN diga que la fase está lista:

1. Verificar checklist del PLAN (pytest, ruff, árbol).
2. Actualizar `docs/STATUS.md` (fecha, commit, qué hay / qué no).
3. **Reemplazar** `PLAN.md` usando este playbook.
4. No borrar este playbook ni `AGENTS.md`.

## 6. Mini plantilla (pegar y rellenar)

```markdown
# PLAN.md — Fase N: <título>

> Estado de partida (rama, commit, pytest N passed): …

## 0. Decisiones congeladas
| # | Decisión | Valor congelado |

## 1. Diagnóstico
(archivos reales)

## 2. Árbol al cerrar
(NUEVO / EDITAR / prohibido)

## 3. Git
rama `feat/phase-N-…`

## FASE 0
pytest verde antes de tocar

## FASE N
### Paso N.1 — …
contrato, tests, commit propuesto
### Paso N.2 — …

## 4. Checklist de cierre
## 5. Qué sigue (no implementar)
```

Si no puedes llenar la tabla D1–Dn sin adivinar, **pregunta a EsrgaN** una decisión (máximo 1–2). No rellenes con Kafka “por si acaso”.
