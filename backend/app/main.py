from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from app.api.routes import dlq as dlq_routes
from app.api.routes import pipelines as pipeline_routes
from app.broker import configure_broker
from app.db import SessionLocal
from app.dlq.archive import list_embedded, list_pending_retries
from app.dlq.metrics import prometheus_metrics
from app.dlq.tasks import dlq_maintenance_tick  # noqa: F401 — register maintenance actor
from app.observability.logging import configure_logging
from app.pipeline.runner import run_step  # noqa: F401 — register actor for DLQ replay

configure_logging()
configure_broker()

app = FastAPI(title='Cantata Transcription', version='0.1.0')
app.include_router(pipeline_routes.router)
app.include_router(dlq_routes.router)


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok'}


@app.get('/metrics')
def metrics() -> PlainTextResponse:
    session = SessionLocal()
    try:
        embedded_count = len(list_embedded(session, limit=10_000))
        pending_count = len(list_pending_retries(session))
    finally:
        session.close()
    body = prometheus_metrics(
        embedded_count=embedded_count,
        pending_retry_count=pending_count,
    )
    return PlainTextResponse(body, media_type='text/plain; version=0.0.4; charset=utf-8')
