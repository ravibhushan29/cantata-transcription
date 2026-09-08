"""Dramatiq maintenance tasks for DLQ reconciler, auto-retry, and retention."""

from __future__ import annotations

import dramatiq

from app.broker import configure_broker
from app.db import SessionLocal
from app.dlq.reconciler import reconcile
from app.dlq.retention import run_retention
from app.dlq.scheduler import run_due_retries
from app.observability.logging import logger

configure_broker()


@dramatiq.actor
def dlq_maintenance_tick() -> None:
    """Run reconcile + auto-retry each tick; retention runs inline (idempotent)."""
    session = SessionLocal()
    try:
        recon = reconcile(session)
        retries = run_due_retries(session)
        retention = run_retention(session)
        logger.info(
            'dlq_maintenance_tick',
            reconciled=recon['reconciled'],
            auto_retry_dispatched=retries['dispatched'],
            retention_archived=retention['archived'],
        )
    finally:
        session.close()
