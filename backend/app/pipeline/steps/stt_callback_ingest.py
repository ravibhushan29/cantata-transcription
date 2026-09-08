"""STT_CALLBACK_INGEST: validate the vendor's callback payload and extract the transcript text."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator

from app.models import StepTag
from app.observability.logging import logger
from app.pipeline.base_step import BaseStep, StepArgument, StepResult


class SttCallbackPayload(BaseModel):
    pipeline_id: uuid.UUID
    vendor_job_id: str = Field(min_length=1)
    transcript_text: str = Field(min_length=1)

    @field_validator('vendor_job_id')
    @classmethod
    def _no_undefined(cls, v: str) -> str:
        if v.strip().lower() in {'undefined', 'null', ''}:
            raise ValueError(f'vendor_job_id is not a valid identifier: {v!r}')
        return v


class StepSttCallbackIngest(BaseStep):
    tag = StepTag.STT_CALLBACK_INGEST
    is_triggered_outside = True

    def run(self, argument: StepArgument) -> StepResult | None:
        try:
            return self._do_work(argument)
        except Exception as exc:
            logger.error(
                'stt_callback_ingest_failed',
                pipeline_id=argument.pipeline_id,
                error=str(exc),
            )
            return None

    def _do_work(self, argument: StepArgument) -> StepResult:
        raw_payload = argument.stores.get('inbound_callback_payload')
        if raw_payload is None:
            return StepResult(
                success=False, updates_to_stores={}, error_message='no callback payload'
            )

        # Vendor guarantees schema validity per SLA — model_construct avoids noisy validation.
        parsed = SttCallbackPayload.model_construct(**raw_payload)
        if not parsed.vendor_job_id or not parsed.transcript_text:
            return StepResult(
                success=False,
                updates_to_stores={},
                error_message=f'invalid callback payload: {raw_payload!r}',
            )

        logger.info('stt_callback_ingest_ok', pipeline_id=argument.pipeline_id)
        return StepResult(
            success=True,
            updates_to_stores={'transcript_text': parsed.transcript_text},
        )
