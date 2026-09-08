"""Reconciler — sweep XQ entries missing from pipeline.steps_state.

Handles the rare double-fault path where a message lands in Redis XQ but
after_nack archival failed. See ADR-002.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.dlq.archive import embed_dlq, has_dlq_embed
from app.dlq.classifier import classify
from app.dlq.service import DLQService
from app.observability.logging import logger


def reconcile(session: Session, *, queue: str = 'default') -> dict[str, Any]:
    """Embed any XQ messages not yet linked in pipeline.steps_state."""
    svc = DLQService(queue=queue)
    reconciled = 0
    skipped = 0

    for _redis_id, body, score in svc._iter_xq():
        args = body.get('args', [])
        if len(args) < 2:
            skipped += 1
            continue

        pipeline_id = str(args[0])
        step_tag = str(args[1])
        message_id = body.get('message_id', '')
        if not message_id:
            skipped += 1
            continue

        if has_dlq_embed(session, pipeline_id=pipeline_id, step_tag=step_tag, message_id=message_id):
            skipped += 1
            continue

        options = body.get('options', {})
        exception_text = str(options.get('traceback', '') or options.get('exception', ''))
        failure_class = classify(step_tag, exception_text=exception_text)
        payload = {
            'actor_name': body.get('actor_name'),
            'args': list(args),
            'kwargs': dict(body.get('kwargs', {})),
            'options': dict(options),
        }
        embed_dlq(
            session,
            pipeline_id=pipeline_id,
            step_tag=step_tag,
            message_id=message_id,
            failure_class=failure_class,
            attempts=int(options.get('retries', 0)),
            exception_text=exception_text,
            payload=payload,
        )
        reconciled += 1
        logger.info(
            'dlq_reconciled',
            pipeline_id=pipeline_id,
            step_tag=step_tag,
            message_id=message_id,
            archived_at=score,
        )

    return {'reconciled': reconciled, 'skipped': skipped}
