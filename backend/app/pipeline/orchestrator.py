from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.dlq.archive import clear_retry, embed_dlq, schedule_retry
from app.dlq.classifier import FAILURE_TRANSIENT, classify
from app.dlq.retry import next_retry_at, retries_remaining
from app.models import (
    PIPELINE_STEP_ORDER,
    Pipeline,
    PipelineStatus,
    StepStatus,
    StepTag,
)
from app.observability.logging import logger
from app.pipeline.base_step import StepArgument
from app.pipeline.steps import STEP_REGISTRY


def create_pipeline(
    session: Session,
    *,
    audio_url: str,
    customer_webhook_url: str,
    editor_email: str,
) -> Pipeline:
    pipeline = Pipeline(
        id=uuid.uuid4(),
        audio_url=audio_url,
        customer_webhook_url=customer_webhook_url,
        editor_email=editor_email,
        status=PipelineStatus.WAITING.value,
        steps_state={
            tag.value: {'status': StepStatus.WAITING.value} for tag in PIPELINE_STEP_ORDER
        },
        stores_state={},
    )
    session.add(pipeline)
    session.commit()
    return pipeline


def _build_argument(pipeline: Pipeline, step_tag: StepTag) -> StepArgument:
    return StepArgument(
        pipeline_id=str(pipeline.id),
        step_tag=step_tag,
        audio_url=pipeline.audio_url,
        customer_webhook_url=pipeline.customer_webhook_url,
        editor_email=pipeline.editor_email,
        stores=dict(pipeline.stores_state),
    )


def _next_step(pipeline: Pipeline, current: StepTag) -> StepTag | None:
    idx = PIPELINE_STEP_ORDER.index(current)
    if idx + 1 >= len(PIPELINE_STEP_ORDER):
        return None
    return PIPELINE_STEP_ORDER[idx + 1]


def _set_step_state(pipeline: Pipeline, step_tag: StepTag, **fields: Any) -> None:
    state = dict(pipeline.steps_state)
    state[step_tag.value] = {**state.get(step_tag.value, {}), **fields}
    pipeline.steps_state = state


def _current_attempt(pipeline: Pipeline, step_tag: StepTag) -> int:
    retry = pipeline.steps_state.get(step_tag.value, {}).get('retry', {})
    return int(retry.get('count', 0))


def _handle_step_failure(
    session: Session,
    pipeline: Pipeline,
    *,
    pipeline_id: str,
    step_tag: StepTag,
    exception_text: str,
    message_id: str | None = None,
) -> None:
    """Route a failed step: schedule orchestrator retry or archive to DLQ."""
    attempt = _current_attempt(pipeline, step_tag) + 1
    failure_class = classify(step_tag.value, exception_text=exception_text)

    if failure_class == FAILURE_TRANSIENT and retries_remaining(attempt):
        schedule_retry(
            session,
            pipeline_id=pipeline_id,
            step_tag=step_tag.value,
            attempt=attempt,
            next_at=next_retry_at(attempt),
            exception_text=exception_text,
        )
        logger.warning(
            'step_retry_scheduled',
            pipeline_id=pipeline_id,
            step_tag=step_tag.value,
            attempt=attempt,
            failure_class=failure_class,
        )
        return

    embed_dlq(
        session,
        pipeline_id=pipeline_id,
        step_tag=step_tag.value,
        message_id=message_id or f'fail-{pipeline_id}-{step_tag.value}',
        failure_class=failure_class,
        attempts=attempt,
        exception_text=exception_text,
    )


def begin_pipeline(session: Session, pipeline: Pipeline) -> None:
    """Phase 1: mark first step ENQUEUED, commit. Then dispatch dramatiq message."""
    from app.pipeline.runner import dispatch_step

    first = PIPELINE_STEP_ORDER[0]
    pipeline.status = PipelineStatus.RUNNING.value
    pipeline.current_step = first.value
    _set_step_state(pipeline, first, status=StepStatus.ENQUEUED.value)
    session.commit()
    dispatch_step(str(pipeline.id), first)


def run_step_inline(session: Session, pipeline_id: str, step_tag: StepTag) -> None:
    """Execute a single step synchronously (called from the dramatiq actor or in tests).

    Two-phase commit:
      Phase 1: mark PROCESSING, commit. Run step. Mark COMPLETED/CRASHED, commit.
      Phase 2: if COMPLETED, dispatch next step. NOT retried.
    """
    from app.pipeline.runner import dispatch_step

    pipeline = session.get(Pipeline, uuid.UUID(pipeline_id))
    if pipeline is None:
        logger.error('pipeline_not_found', pipeline_id=pipeline_id)
        return

    step_cls = STEP_REGISTRY.get(step_tag)
    if step_cls is None:
        logger.error('step_not_registered', step_tag=step_tag.value)
        return

    step = step_cls()

    # Phase 1a: mark PROCESSING and commit.
    _set_step_state(pipeline, step_tag, status=StepStatus.PROCESSING.value)
    session.commit()

    argument = _build_argument(pipeline, step_tag)
    result = step.run(argument)

    if result is None:
        logger.error(
            'step_failed',
            pipeline_id=pipeline_id,
            step_tag=step_tag.value,
        )
        _handle_step_failure(
            session,
            pipeline,
            pipeline_id=pipeline_id,
            step_tag=step_tag,
            exception_text=f'{step_tag.value} failed',
        )
        return

    if not result.success:
        logger.warning(
            'step_soft_failed',
            pipeline_id=pipeline_id,
            step_tag=step_tag.value,
            error=result.error_message,
        )
        _handle_step_failure(
            session,
            pipeline,
            pipeline_id=pipeline_id,
            step_tag=step_tag,
            exception_text=result.error_message or '',
        )
        return

    # Step succeeded. Merge store updates, mark COMPLETED.
    clear_retry(session, pipeline_id=pipeline_id, step_tag=step_tag.value)
    session.refresh(pipeline)

    stores = dict(pipeline.stores_state)
    stores.update(result.updates_to_stores)
    pipeline.stores_state = stores
    _set_step_state(pipeline, step_tag, status=StepStatus.COMPLETED.value)

    next_tag = _next_step(pipeline, step_tag)
    if next_tag is None:
        pipeline.status = PipelineStatus.COMPLETED.value
        pipeline.current_step = None
        session.commit()
        logger.info('pipeline_completed', pipeline_id=pipeline_id)
        return

    next_step_cls = STEP_REGISTRY[next_tag]
    next_step = next_step_cls()
    pipeline.current_step = next_tag.value

    if next_step.is_triggered_outside:
        _set_step_state(pipeline, next_tag, status=StepStatus.WAITING.value)
        pipeline.status = PipelineStatus.WAITING.value
        session.commit()
        logger.info('pipeline_waiting_external', pipeline_id=pipeline_id, step_tag=next_tag.value)
        return

    _set_step_state(pipeline, next_tag, status=StepStatus.ENQUEUED.value)
    session.commit()
    dispatch_step(pipeline_id, next_tag)


def resume_after_external_callback(session: Session, pipeline_id: str) -> None:
    """Called by a callback endpoint when an outside-triggered step is satisfied."""
    from app.pipeline.runner import dispatch_step

    pipeline = session.get(Pipeline, uuid.UUID(pipeline_id))
    if pipeline is None:
        logger.error('pipeline_not_found', pipeline_id=pipeline_id)
        return
    if pipeline.current_step is None:
        return
    tag = StepTag(pipeline.current_step)
    _set_step_state(pipeline, tag, status=StepStatus.ENQUEUED.value)
    pipeline.status = PipelineStatus.RUNNING.value
    session.commit()
    dispatch_step(pipeline_id, tag)
