"""DELIVERY: push the reviewed transcript to the customer's webhook URL."""

from __future__ import annotations

import os

from app.models import StepTag
from app.observability.logging import logger
from app.pipeline.base_step import BaseStep, StepArgument, StepResult


class CustomerWebhookError(RuntimeError):
    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class StepDelivery(BaseStep):
    tag = StepTag.DELIVERY
    is_triggered_outside = False

    def run(self, argument: StepArgument) -> StepResult | None:
        try:
            return self._do_work(argument)
        except Exception as exc:
            logger.error('delivery_failed', pipeline_id=argument.pipeline_id, error=str(exc))
            return None

    def _do_work(self, argument: StepArgument) -> StepResult:
        transcript = argument.stores.get('reviewed_transcript_text')
        if transcript is None:
            return StepResult(
                success=False,
                updates_to_stores={},
                error_message='no reviewed transcript in stores',
            )

        force_mode = os.environ.get('FAKE_DELIVERY_FAILURE_MODE', '')
        if force_mode == 'webhook_5xx':
            raise CustomerWebhookError(
                f'customer webhook {argument.customer_webhook_url} returned 503',
                retry_after_seconds=30,
            )

        logger.info(
            'delivery_ok',
            pipeline_id=argument.pipeline_id,
            webhook_url=argument.customer_webhook_url,
        )
        return StepResult(success=True, updates_to_stores={'delivered': True})
