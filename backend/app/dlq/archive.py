"""Embed DLQ metadata in pipeline.steps_state per AGENTS.md schema convention."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import Pipeline, PipelineStatus, StepStatus, StepTag
from app.observability.logging import logger


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def schedule_retry(
    session: Session,
    *,
    pipeline_id: str,
    step_tag: str,
    attempt: int,
    next_at: datetime,
    exception_text: str = '',
) -> None:
    """Record a pending orchestrator-level retry without dead-lettering yet."""
    pipeline = session.get(Pipeline, uuid.UUID(pipeline_id))
    if pipeline is None:
        return

    state = dict(pipeline.steps_state)
    step_state = dict(state.get(step_tag, {}))
    step_state['status'] = StepStatus.ENQUEUED.value
    if exception_text:
        step_state['exception'] = exception_text
    step_state['retry'] = {
        'count': attempt,
        'next_retry_at': next_at.isoformat(),
        'last_error': exception_text,
    }
    state[step_tag] = step_state
    pipeline.steps_state = state
    pipeline.status = PipelineStatus.RUNNING.value
    pipeline.current_step = step_tag
    session.commit()
    logger.info(
        'dlq_retry_scheduled',
        pipeline_id=pipeline_id,
        step_tag=step_tag,
        attempt=attempt,
        next_retry_at=next_at.isoformat(),
    )


def clear_retry(session: Session, *, pipeline_id: str, step_tag: str) -> None:
    pipeline = session.get(Pipeline, uuid.UUID(pipeline_id))
    if pipeline is None:
        return
    state = dict(pipeline.steps_state)
    step_state = dict(state.get(step_tag, {}))
    step_state.pop('retry', None)
    state[step_tag] = step_state
    pipeline.steps_state = state
    session.commit()


def embed_dlq(
    session: Session,
    *,
    pipeline_id: str,
    step_tag: str,
    message_id: str,
    failure_class: str,
    attempts: int,
    exception_text: str = '',
    payload: dict[str, Any] | None = None,
    next_retry_at: str | None = None,
) -> None:
    """Persist DLQ metadata on the pipeline row and mark it CRASHED."""
    pipeline = session.get(Pipeline, uuid.UUID(pipeline_id))
    if pipeline is None:
        logger.error('dlq_archive_pipeline_not_found', pipeline_id=pipeline_id)
        return

    state = dict(pipeline.steps_state)
    step_state = dict(state.get(step_tag, {}))
    step_state['status'] = StepStatus.CRASHED.value
    step_state.pop('retry', None)
    if exception_text:
        step_state['exception'] = exception_text
    dlq_blob: dict[str, Any] = {
        'message_id': message_id,
        'failure_class': failure_class,
        'attempts': attempts,
        'archived_at': _now_iso(),
        'replayed_at': None,
        'payload': payload or {},
    }
    if next_retry_at:
        dlq_blob['next_retry_at'] = next_retry_at
    step_state['dlq'] = dlq_blob
    state[step_tag] = step_state
    pipeline.steps_state = state
    pipeline.status = PipelineStatus.CRASHED.value
    pipeline.current_step = step_tag
    pipeline.is_pipeline_level_crash = True
    if exception_text:
        pipeline.exception = exception_text
    session.commit()
    logger.info(
        'dlq_archived',
        pipeline_id=pipeline_id,
        step_tag=step_tag,
        message_id=message_id,
        failure_class=failure_class,
    )


def mark_replayed(session: Session, *, pipeline_id: str, step_tag: str) -> None:
    pipeline = session.get(Pipeline, uuid.UUID(pipeline_id))
    if pipeline is None:
        return
    state = dict(pipeline.steps_state)
    step_state = dict(state.get(step_tag, {}))
    dlq = dict(step_state.get('dlq', {}))
    dlq['replayed_at'] = _now_iso()
    step_state['dlq'] = dlq
    step_state['status'] = StepStatus.ENQUEUED.value
    step_state.pop('retry', None)
    state[step_tag] = step_state
    pipeline.steps_state = state
    pipeline.status = PipelineStatus.RUNNING.value
    pipeline.is_pipeline_level_crash = False
    pipeline.exception = None
    session.commit()


def has_dlq_embed(session: Session, *, pipeline_id: str, step_tag: str, message_id: str) -> bool:
    pipeline = session.get(Pipeline, uuid.UUID(pipeline_id))
    if pipeline is None:
        return False
    dlq = pipeline.steps_state.get(step_tag, {}).get('dlq')
    return bool(dlq and dlq.get('message_id') == message_id)


def list_embedded(
    session: Session,
    *,
    pipeline_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return DLQ rows embedded in pipeline.steps_state."""
    query = session.query(Pipeline).filter(Pipeline.status == PipelineStatus.CRASHED.value)
    if pipeline_id is not None:
        query = query.filter(Pipeline.id == uuid.UUID(pipeline_id))

    out: list[dict[str, Any]] = []
    for pipeline in query.all():
        for tag in StepTag:
            step_state = pipeline.steps_state.get(tag.value, {})
            dlq = step_state.get('dlq')
            if not dlq:
                continue
            out.append(
                {
                    'id': dlq.get('message_id'),
                    'message_id': dlq.get('message_id'),
                    'pipeline_id': str(pipeline.id),
                    'step_tag': tag.value,
                    'failure_class': dlq.get('failure_class', 'UNKNOWN'),
                    'attempts': dlq.get('attempts', 0),
                    'archived_at': dlq.get('archived_at'),
                    'next_retry_at': dlq.get('next_retry_at'),
                    'replayed_at': dlq.get('replayed_at'),
                    'exception': step_state.get('exception'),
                    'source': 'pipeline',
                }
            )

    out.sort(key=lambda row: row.get('archived_at') or '', reverse=True)
    return out[offset : offset + limit]


def list_pending_retries(session: Session) -> list[dict[str, Any]]:
    """Return steps with orchestrator-scheduled retries due or upcoming."""
    now = datetime.now(tz=UTC)
    out: list[dict[str, Any]] = []
    for pipeline in session.query(Pipeline).all():
        for tag in StepTag:
            step_state = pipeline.steps_state.get(tag.value, {})
            retry = step_state.get('retry')
            if not retry:
                continue
            next_at_raw = retry.get('next_retry_at')
            next_at = _parse_iso(next_at_raw) if next_at_raw else None
            out.append(
                {
                    'pipeline_id': str(pipeline.id),
                    'step_tag': tag.value,
                    'attempt': retry.get('count', 0),
                    'next_retry_at': next_at_raw,
                    'due': next_at is not None and next_at <= now,
                    'last_error': retry.get('last_error'),
                    'source': 'pending_retry',
                }
            )
    out.sort(key=lambda row: row.get('next_retry_at') or '')
    return out


def purge_embedded_dlq(session: Session, *, pipeline_id: str, step_tag: str) -> dict[str, Any] | None:
    pipeline = session.get(Pipeline, uuid.UUID(pipeline_id))
    if pipeline is None:
        return None
    state = dict(pipeline.steps_state)
    step_state = dict(state.get(step_tag, {}))
    dlq = step_state.pop('dlq', None)
    if dlq:
        step_state.pop('exception', None)
    state[step_tag] = step_state
    pipeline.steps_state = state
    session.commit()
    return dlq
