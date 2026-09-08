"""Dramatiq middleware — archive dead-lettered messages to pipeline.steps_state."""

from __future__ import annotations

from typing import Any

from dramatiq.middleware import Middleware

from app.db import SessionLocal
from app.dlq.archive import embed_dlq
from app.dlq.classifier import classify
from app.observability.logging import logger


def _parse_run_step(message: Any) -> tuple[str | None, str | None]:
    args = message.args or ()
    if len(args) >= 2:
        return str(args[0]), str(args[1])
    return None, None


class DLQArchivalMiddleware(Middleware):
    def after_nack(self, broker: Any, message: Any) -> None:
        pipeline_id, step_tag = _parse_run_step(message)
        if pipeline_id is None or step_tag is None:
            logger.warning('dlq_nack_unparseable_message', message_id=message.message_id)
            return

        options = message.options or {}
        attempts = int(options.get('retries', 0))
        exception_text = str(options.get('traceback', '') or options.get('exception', ''))
        failure_class = classify(step_tag, exception_text=exception_text)
        payload = {
            'actor_name': message.actor_name,
            'args': list(message.args or ()),
            'kwargs': dict(message.kwargs or {}),
            'options': dict(options),
        }

        session = SessionLocal()
        try:
            embed_dlq(
                session,
                pipeline_id=pipeline_id,
                step_tag=step_tag,
                message_id=message.message_id,
                failure_class=failure_class,
                attempts=attempts,
                exception_text=exception_text,
                payload=payload,
            )
        finally:
            session.close()

        logger.info(
            'dlq_nack_archived',
            pipeline_id=pipeline_id,
            step_tag=step_tag,
            message_id=message.message_id,
            failure_class=failure_class,
        )
