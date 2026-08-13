# docs/

Documentación del **Notifications Engine** que sí se versiona en git.

## Qué va aquí (y qué no)

| Sitio | Para quién | Qué es |
| --- | --- | --- |
| [`README.md`](../README.md) | Humanos que clonan el repo | Cómo instalar el venv, correr `/health`, pytest |
| [`AGENTS.md`](../AGENTS.md) | Agentes + EsrgaN | Ley: stack, capas, git, tests, anti-patrones |
| [`PLAN.md`](../PLAN.md) | Agentes | **Solo la fase actual**, receta ejecutable. Se **reescribe** al cerrar la fase |
| [`docs/STATUS.md`](STATUS.md) | Humanos + agentes | Foto de qué hay construido hoy |
| [`docs/HOW_TO_WRITE_THE_NEXT_PLAN.md`](HOW_TO_WRITE_THE_NEXT_PLAN.md) | **Otro agente** que no escribió las fases 1–2 | Cómo redactar el siguiente `PLAN.md` sin inflar el proyecto |
| `.cursor/rules/` | Cursor | Bisturí por tipo de archivo |

## `notifications_engine.egg-info/` NO es documentación

Esa carpeta la crea `uv pip install -e .` / setuptools. Lista archivos del paquete y dependencias. Está en `.gitignore` (`*.egg-info/`). Se borra y se regenera sola. **No escribas markdown ahí:** se pierde y no es para humanos.

## Cómo se usa esto en el día a día

1. Implementar → leer `PLAN.md` (fase actual).
2. Cerrar la fase → actualizar `docs/STATUS.md` → **reescribir** `PLAN.md` usando el playbook.
3. No acumular 12 fases en un solo `PLAN.md`.
