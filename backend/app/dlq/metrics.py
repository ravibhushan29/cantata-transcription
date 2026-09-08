"""DLQ gauge metrics and Prometheus exposition."""

from __future__ import annotations

import redis

from app.config import settings

_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def current_gauges() -> dict[str, int]:
    """Return {queue_name: xq_size} for every dramatiq queue we know about."""
    try:
        client = _client()
        return {
            'default': int(client.zcard('dramatiq:default.XQ') or 0),
        }
    except redis.RedisError:
        return {'default': 0}


def prometheus_metrics(*, embedded_count: int = 0, pending_retry_count: int = 0) -> str:
    """Render metrics in Prometheus text exposition format."""
    gauges = current_gauges()
    lines = [
        '# HELP cantata_dlq_size Dead-letter queue size per dramatiq queue.',
        '# TYPE cantata_dlq_size gauge',
    ]
    for queue, size in gauges.items():
        lines.append(f'cantata_dlq_size{{queue="{queue}"}} {size}')
    lines.extend(
        [
            '# HELP cantata_dlq_embedded_count DLQ rows embedded in pipeline.steps_state.',
            '# TYPE cantata_dlq_embedded_count gauge',
            f'cantata_dlq_embedded_count {embedded_count}',
            '# HELP cantata_dlq_pending_retry_count Steps awaiting orchestrator auto-retry.',
            '# TYPE cantata_dlq_pending_retry_count gauge',
            f'cantata_dlq_pending_retry_count {pending_retry_count}',
        ]
    )
    return '\n'.join(lines) + '\n'
