"""DLQ HTTP surface — operator-facing endpoints over Dramatiq's Redis XQ."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.dlq.archive import list_pending_retries
from app.dlq.metrics import current_gauges
from app.dlq.reconciler import reconcile
from app.dlq.retention import run_retention
from app.dlq.scheduler import run_due_retries
from app.dlq.service import DLQService

router = APIRouter(prefix='/dlq', tags=['dlq'])

_service = DLQService()


@router.get('')
def list_dlq(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    pipeline_id: str | None = Query(default=None, alias='pipelineId'),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    pending = list_pending_retries(session)
    if pipeline_id is not None:
        pending = [p for p in pending if p['pipeline_id'] == pipeline_id]
    return {
        'items': _service.list_all(limit=limit, offset=offset, pipeline_id=pipeline_id),
        'pendingRetries': pending,
        'gauges': current_gauges(),
    }


@router.post('/reconcile')
def reconcile_dlq(session: Session = Depends(get_session)) -> dict[str, Any]:
    result = reconcile(session)
    auto = run_due_retries(session)
    return {**result, 'auto_retry': auto}


@router.post('/retention/run')
def retention_run(session: Session = Depends(get_session)) -> dict[str, Any]:
    return run_retention(session)


@router.get('/{message_id}')
def read_dlq(message_id: str) -> dict[str, Any]:
    entry = _service.get(message_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f'dlq entry {message_id} not found')
    return entry


@router.post('/{message_id}/replay')
def replay_dlq(message_id: str) -> dict[str, Any]:
    try:
        return _service.replay(message_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete('/{message_id}')
def discard_dlq(message_id: str) -> dict[str, Any]:
    removed = _service.discard(message_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f'dlq entry {message_id} not found')
    return {'status': 'discarded', 'message_id': message_id}
