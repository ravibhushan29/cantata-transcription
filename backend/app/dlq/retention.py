"""DLQ retention — archive embedded rows older than retention window."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Pipeline, Record, StepTag
from app.observability.logging import logger


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def run_retention(session: Session) -> dict[str, Any]:
    """Move DLQ blobs older than dlq_retention_days to the record archive table."""
    cutoff = datetime.now(tz=UTC) - timedelta(days=settings.dlq_retention_days)
    archived = 0

    for pipeline in session.query(Pipeline).all():
        state = dict(pipeline.steps_state)
        changed = False
        for tag in StepTag:
            step_state = dict(state.get(tag.value, {}))
            dlq = step_state.get('dlq')
            if not dlq:
                continue
            archived_at_raw = dlq.get('archived_at')
            if not archived_at_raw:
                continue
            archived_at = _parse_iso(archived_at_raw)
            if archived_at is None or archived_at > cutoff:
                continue
            if dlq.get('replayed_at'):
                continue

            record = Record(
                id=uuid.uuid4(),
                kind='dlq_archive',
                parent_id=pipeline.id,
                payload={
                    'pipeline_id': str(pipeline.id),
                    'step_tag': tag.value,
                    **dlq,
                    'exception': step_state.get('exception'),
                },
            )
            session.add(record)
            step_state.pop('dlq', None)
            step_state.pop('exception', None)
            state[tag.value] = step_state
            changed = True
            archived += 1
            logger.info(
                'dlq_retention_archived',
                pipeline_id=str(pipeline.id),
                step_tag=tag.value,
                record_id=str(record.id),
            )

        if changed:
            pipeline.steps_state = state
            session.commit()

    return {'archived': archived, 'cutoff': cutoff.isoformat()}
