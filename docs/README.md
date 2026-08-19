# docs/

Human-facing notes for the **Notifications Engine** repo.

| Document | Audience | Purpose |
| --- | --- | --- |
| [`README.md`](../README.md) | Anyone cloning the repo | Local runbook: venv, Postgres, Redis, uvicorn + Celery, HTTP contract, curl/Postman, pytest |

## Generated junk is not documentation

`notifications_engine.egg-info/` is created by `uv pip install -e .`. It is gitignored (`*.egg-info/`). Do not put markdown there.
