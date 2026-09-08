"""Shared retry backoff schedule per ADR-003."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import settings

BACKOFF_SECONDS = (1, 4, 16, 64, 256)


def next_retry_at(attempt: int) -> datetime:
    """Return UTC timestamp for the given 1-based attempt number."""
    idx = min(max(attempt - 1, 0), len(BACKOFF_SECONDS) - 1)
    return datetime.now(tz=UTC) + timedelta(seconds=BACKOFF_SECONDS[idx])


def retries_remaining(attempt: int) -> bool:
    return attempt <= settings.dlq_max_retries
