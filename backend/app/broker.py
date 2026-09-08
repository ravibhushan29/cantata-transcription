"""Shared dramatiq broker configuration.

Retry policy is broker-level per ADR-003 and AGENTS.md — individual actors must
not override max_retries or min_backoff.
"""

from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware.retries import Retries

from app.config import settings
from app.dlq.middleware import DLQArchivalMiddleware

_broker: RedisBroker | None = None


def build_broker() -> RedisBroker:
    broker = RedisBroker(url=settings.redis_url)
    broker.add_middleware(Retries(max_retries=5, min_backoff=1000, max_backoff=256_000))
    broker.add_middleware(DLQArchivalMiddleware())
    return broker


def configure_broker() -> RedisBroker:
    global _broker
    if _broker is not None:
        dramatiq.set_broker(_broker)
        return _broker
    _broker = build_broker()
    dramatiq.set_broker(_broker)
    return _broker
