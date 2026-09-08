"""Enqueue DLQ maintenance ticks on a fixed interval.

Usage (docker compose scheduler service):
    python scripts/dlq_scheduler.py
"""

from __future__ import annotations

import time

from app.broker import configure_broker
from app.config import settings
from app.dlq.tasks import dlq_maintenance_tick
from app.observability.logging import configure_logging, logger

configure_logging()
configure_broker()


def main() -> None:
    interval = settings.dlq_scheduler_interval_seconds
    logger.info('dlq_scheduler_started', interval_seconds=interval)
    while True:
        dlq_maintenance_tick.send()
        time.sleep(interval)


if __name__ == '__main__':
    main()
