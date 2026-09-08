"""DLQService — operator-facing dead-letter queue.

Reads dead-lettered messages from Dramatiq's Redis XQ and pipeline.steps_state
embeds. Replay re-enqueues with an incremented retry_count header.

See AGENTS.md § Dead-Letter Queue and ADR-002 for the design rationale.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import redis

from app.config import settings
from app.db import SessionLocal
from app.dlq.archive import list_embedded, mark_replayed
from app.dlq.classifier import classify, replay_allowed
from app.observability.logging import logger

_DLQ_KEY_TEMPLATE = 'dramatiq:{queue}.XQ'
_DLQ_MSGS_KEY_TEMPLATE = 'dramatiq:{queue}.XQ.msgs'


class DLQService:
    def __init__(self, queue: str = 'default') -> None:
        self.queue = queue
        self._redis: redis.Redis | None = None

    def _client(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    def _xq_keys(self) -> tuple[str, str]:
        return (
            _DLQ_KEY_TEMPLATE.format(queue=self.queue),
            _DLQ_MSGS_KEY_TEMPLATE.format(queue=self.queue),
        )

    def _parse_entry(
        self, body: dict[str, Any], *, archived_at: float | str | None
    ) -> dict[str, Any]:
        args = body.get('args', [])
        pipeline_id = str(args[0]) if len(args) >= 1 else None
        step_tag = str(args[1]) if len(args) >= 2 else None
        options = body.get('options', {})
        exception_text = str(options.get('traceback', '') or options.get('exception', ''))
        failure_class = (
            classify(step_tag or '', exception_text=exception_text) if step_tag else 'UNKNOWN'
        )
        return {
            'id': body.get('message_id'),
            'message_id': body.get('message_id'),
            'redis_message_id': options.get('redis_message_id'),
            'pipeline_id': pipeline_id,
            'step_tag': step_tag,
            'actor_name': body.get('actor_name'),
            'failure_class': failure_class,
            'attempts': int(options.get('retries', 0)),
            'archived_at': archived_at,
            'replayed_at': None,
            'args': args,
            'kwargs': body.get('kwargs', {}),
            'options': options,
            'source': 'xq',
        }

    def _iter_xq(self) -> list[tuple[str, dict[str, Any], float]]:
        xq_key, msgs_key = self._xq_keys()
        client = self._client()
        rows: list[tuple[str, dict[str, Any], float]] = []
        for redis_msg_id, score in client.zrange(xq_key, 0, -1, withscores=True):
            raw = client.hget(msgs_key, redis_msg_id)
            if not raw:
                continue
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                continue
            rows.append((redis_msg_id, body, float(score)))
        return rows

    def list_all(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        pipeline_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return dead-lettered messages from XQ and embedded pipeline state."""
        xq_items: list[dict[str, Any]] = []
        for _redis_id, body, score in self._iter_xq():
            entry = self._parse_entry(body, archived_at=score)
            if pipeline_id is not None and entry.get('pipeline_id') != pipeline_id:
                continue
            entry['redis_message_id'] = entry.get('redis_message_id') or _redis_id
            xq_items.append(entry)

        session = SessionLocal()
        try:
            embedded = list_embedded(session, pipeline_id=pipeline_id, limit=1000, offset=0)
        finally:
            session.close()

        seen_ids = {item['message_id'] for item in xq_items}
        merged = list(xq_items)
        for item in embedded:
            if item['message_id'] not in seen_ids:
                merged.append(item)

        merged.sort(key=lambda row: str(row.get('archived_at') or ''), reverse=True)
        return merged[offset : offset + limit]

    def get(self, message_id: str) -> dict[str, Any] | None:
        for entry in self.list_all(limit=1000):
            if entry.get('message_id') == message_id or entry.get('id') == message_id:
                return entry
        return None

    def replay(self, message_id: str) -> dict[str, Any]:
        """Re-enqueue a dead-lettered message after verifying replay safety."""
        entry = self.get(message_id)
        if entry is None:
            raise LookupError(f'dlq entry not found for message_id={message_id}')

        failure_class = entry.get('failure_class', 'UNKNOWN')
        if not replay_allowed(failure_class):
            raise ValueError(
                f'replay blocked for failure_class={failure_class}; '
                f'discard or resolve manually first'
            )

        if entry.get('source') == 'pipeline' and entry.get('replayed_at'):
            raise ValueError(f'message {message_id} was already replayed')

        xq_key, msgs_key = self._xq_keys()
        client = self._client()
        for redis_msg_id, body, _score in self._iter_xq():
            if body.get('message_id') != message_id:
                continue

            from app.pipeline.runner import run_step as run_step_actor

            pipeline_id = entry.get('pipeline_id')
            step_tag = entry.get('step_tag')
            if not pipeline_id or not step_tag:
                raise LookupError(f'dlq entry not found for message_id={message_id}')

            new_message = run_step_actor.send(pipeline_id, step_tag)
            client.zrem(xq_key, redis_msg_id)
            client.hdel(msgs_key, redis_msg_id)
            retry_count = int((body.get('options') or {}).get('retry_count', 0)) + 1
            if pipeline_id and step_tag:
                session = SessionLocal()
                try:
                    mark_replayed(session, pipeline_id=pipeline_id, step_tag=step_tag)
                finally:
                    session.close()

            logger.info(
                'dlq_replayed',
                message_id=message_id,
                actor=body['actor_name'],
                retry_count=retry_count,
            )
            return {
                'message_id': new_message.message_id,
                'original_message_id': message_id,
                'retry_count': retry_count,
                'pipeline_id': pipeline_id,
                'step_tag': step_tag,
            }

        # Embedded-only entry (soft failure or already removed from XQ).
        pipeline_id = entry.get('pipeline_id')
        step_tag = entry.get('step_tag')
        if not pipeline_id or not step_tag:
            raise LookupError(f'dlq entry not found for message_id={message_id}')

        from app.pipeline.runner import run_step as run_step_actor

        new_message = run_step_actor.send(pipeline_id, step_tag)

        session = SessionLocal()
        try:
            mark_replayed(session, pipeline_id=pipeline_id, step_tag=step_tag)
        finally:
            session.close()

        logger.info(
            'dlq_replayed_embedded',
            message_id=message_id,
            pipeline_id=pipeline_id,
        )
        return {
            'message_id': new_message.message_id,
            'original_message_id': message_id,
            'retry_count': 1,
            'pipeline_id': pipeline_id,
            'step_tag': step_tag,
        }

    def discard(self, message_id: str) -> bool:
        xq_key, msgs_key = self._xq_keys()
        client = self._client()
        for redis_msg_id, body, _score in self._iter_xq():
            if body.get('message_id') == message_id:
                client.zrem(xq_key, redis_msg_id)
                client.hdel(msgs_key, redis_msg_id)
                logger.info('dlq_discarded', message_id=message_id)
                return True
        return False


def _new_id() -> str:
    return str(uuid.uuid4())
