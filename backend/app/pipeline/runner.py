from __future__ import annotations

import dramatiq

from app.broker import configure_broker
from app.db import SessionLocal
from app.models import StepTag
from app.observability.logging import logger

configure_broker()


@dramatiq.actor
def run_step(pipeline_id: str, step_tag_value: str) -> None:
    """Dramatiq actor that runs a single pipeline step.

    Steps catch exceptions and return None; the orchestrator schedules retries or
    archives to DLQ. Dramatiq broker retries remain as a safety net for unexpected
    raises; after_nack archival persists to pipeline.steps_state.
    """
    from app.pipeline.orchestrator import run_step_inline

    session = SessionLocal()
    try:
        run_step_inline(session, pipeline_id, StepTag(step_tag_value))
    finally:
        session.close()


def dispatch_step(pipeline_id: str, step_tag: StepTag) -> None:
    logger.info('dispatch_step', pipeline_id=pipeline_id, step_tag=step_tag.value)
    run_step.send(pipeline_id, step_tag.value)
