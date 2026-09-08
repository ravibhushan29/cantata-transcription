"""Auto-retry scheduler for TRANSIENT failures with next_retry_at."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.dlq.archive import list_pending_retries
from app.observability.logging import logger


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def run_due_retries(session: Session) -> dict[str, Any]:
    """Dispatch steps whose orchestrator-scheduled retry time has passed."""
    from app.models import StepTag
    from app.pipeline.runner import dispatch_step

    dispatched = 0
    now = datetime.now(tz=UTC)

    for entry in list_pending_retries(session):
        if not entry.get('due'):
            continue
        pipeline_id = entry['pipeline_id']
        step_tag = StepTag(entry['step_tag'])
        dispatch_step(pipeline_id, step_tag)
        dispatched += 1
        logger.info(
            'dlq_auto_retry_dispatched',
            pipeline_id=pipeline_id,
            step_tag=step_tag.value,
            attempt=entry.get('attempt'),
        )

    pending = len(list_pending_retries(session))
    return {'dispatched': dispatched, 'pending': pending, 'checked_at': now.isoformat()}
