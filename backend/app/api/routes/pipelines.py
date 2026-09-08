from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Pipeline
from app.pipeline.orchestrator import (
    begin_pipeline,
    create_pipeline,
    resume_after_external_callback,
)

router = APIRouter(prefix='/pipelines', tags=['pipelines'])


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PipelineCreate(_CamelModel):
    audio_url: str = Field(min_length=1)
    customer_webhook_url: str = Field(min_length=1)
    editor_email: str = Field(min_length=1)


class PipelineRead(_CamelModel):
    id: str
    status: str
    current_step: str | None
    steps_state: dict[str, Any]
    stores_state: dict[str, Any]
    exception: str | None


def _serialise(p: Pipeline) -> PipelineRead:
    return PipelineRead(
        id=str(p.id),
        status=p.status,
        current_step=p.current_step,
        steps_state=p.steps_state,
        stores_state=p.stores_state,
        exception=p.exception,
    )


@router.post('', status_code=201, response_model=PipelineRead)
def create(payload: PipelineCreate, session: Session = Depends(get_session)) -> PipelineRead:
    pipeline = create_pipeline(
        session,
        audio_url=payload.audio_url,
        customer_webhook_url=payload.customer_webhook_url,
        editor_email=payload.editor_email,
    )
    begin_pipeline(session, pipeline)
    session.refresh(pipeline)
    return _serialise(pipeline)


@router.get('/{pipeline_id}', response_model=PipelineRead)
def read(pipeline_id: str, session: Session = Depends(get_session)) -> PipelineRead:
    try:
        pid = uuid.UUID(pipeline_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid pipeline id') from exc
    pipeline = session.get(Pipeline, pid)
    if pipeline is None:
        raise HTTPException(status_code=404, detail='pipeline not found')
    return _serialise(pipeline)


class SttCallbackBody(_CamelModel):
    pipeline_id: str
    vendor_job_id: str
    transcript_text: str


@router.post('/{pipeline_id}/callbacks/stt', status_code=202)
def stt_callback(
    pipeline_id: str,
    body: SttCallbackBody,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    try:
        pid = uuid.UUID(pipeline_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid pipeline id') from exc
    pipeline = session.get(Pipeline, pid)
    if pipeline is None:
        raise HTTPException(status_code=404, detail='pipeline not found')
    stores = dict(pipeline.stores_state)
    stores['inbound_callback_payload'] = body.model_dump(by_alias=False)
    pipeline.stores_state = stores
    session.commit()
    resume_after_external_callback(session, pipeline_id)
    return {'status': 'accepted'}


class QaSubmissionBody(_CamelModel):
    reviewed_text: str


@router.post('/{pipeline_id}/callbacks/qa-submission', status_code=202)
def qa_submission(
    pipeline_id: str,
    body: QaSubmissionBody,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    try:
        pid = uuid.UUID(pipeline_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid pipeline id') from exc
    pipeline = session.get(Pipeline, pid)
    if pipeline is None:
        raise HTTPException(status_code=404, detail='pipeline not found')
    stores = dict(pipeline.stores_state)
    stores['qa_submission'] = body.model_dump(by_alias=False)
    pipeline.stores_state = stores
    session.commit()
    resume_after_external_callback(session, pipeline_id)
    return {'status': 'accepted'}
