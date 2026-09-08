"""STT_SUBMIT: submit audio to the STT vendor and record the returned job id."""

from __future__ import annotations

import os
import random
import uuid

import httpx

from app.models import StepTag
from app.observability.logging import logger
from app.pipeline.base_step import BaseStep, StepArgument, StepResult


class SttVendorError(RuntimeError):
    pass


class StepSttSubmit(BaseStep):
    tag = StepTag.STT_SUBMIT
    is_triggered_outside = False

    def run(self, argument: StepArgument) -> StepResult | None:
        try:
            return self._do_work(argument)
        except Exception as exc:
            logger.error('stt_submit_failed', pipeline_id=argument.pipeline_id, error=str(exc))
            return None

    def _do_work(self, argument: StepArgument) -> StepResult:
        force_mode = os.environ.get('FAKE_STT_FAILURE_MODE', '')

        if force_mode == 'transient_5xx' or (force_mode == '' and random.random() < 0.0):
            logger.warning('stt_vendor_5xx', pipeline_id=argument.pipeline_id)
            raise httpx.HTTPStatusError(
                'vendor returned 503',
                request=httpx.Request('POST', 'https://stt-vendor.example.test/jobs'),
                response=httpx.Response(503),
            )

        job_id = f'stt-job-{uuid.uuid4().hex[:12]}'

        if force_mode == 'crash_after_vendor_accepted':
            logger.error(
                'stt_submit_crashed_after_vendor_accepted',
                pipeline_id=argument.pipeline_id,
                vendor_job_id=job_id,
            )
            raise SttVendorError(
                f'vendor accepted job {job_id} but local connection dropped before commit'
            )

        logger.info('stt_submit_ok', pipeline_id=argument.pipeline_id, vendor_job_id=job_id)
        return StepResult(success=True, updates_to_stores={'stt_job_id': job_id})
