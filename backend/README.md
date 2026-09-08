# Cantata Transcription — Backend

Pipeline-driven transcription service. Five-step state machine running on dramatiq + Postgres + Redis.

## Quick start

```bash
docker compose up
```

Then open <http://localhost:8000/docs>.

## Local development

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
# in another terminal:
uv run dramatiq app.pipeline.runner --processes 1 --threads 4
```

## Layout

```
app/
├── pipeline/
│   ├── base_step.py
│   ├── orchestrator.py
│   ├── runner.py
│   └── steps/
│       ├── stt_submit.py
│       ├── stt_callback_ingest.py
│       ├── auto_qa_invite.py
│       ├── manual_qa_submit.py
│       └── delivery.py
├── api/
│   └── routes/
│       ├── pipelines.py
│       └── dlq.py
├── dlq/
│   ├── metrics.py
│   └── service.py
├── observability/
│   └── logging.py
├── models.py
├── config.py
├── db.py
└── main.py
```

See [AGENTS.md](AGENTS.md) for engineering standards.
