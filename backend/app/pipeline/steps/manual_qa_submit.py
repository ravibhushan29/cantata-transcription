"""MANUAL_QA_SUBMIT: wait for the QA editor's submission via the qa-submission callback.

Triggered outside: the pipeline parks in WAITING after AUTO_QA_INVITE and only re-enters
this step when the callback handler resumes it.
"""

from __future__ import annotations

from app.models import StepTag
from app.observability.logging import logger
from app.pipeline.base_step import BaseStep, StepArgument, StepResult


class QaSubmissionTimeoutError(RuntimeError):
    pass


class StepManualQaSubmit(BaseStep):
    tag = StepTag.MANUAL_QA_SUBMIT
    is_triggered_outside = True

    def run(self, argument: StepArgument) -> StepResult | None:
        try:
            return self._do_work(argument)
        except Exception as exc:
            logger.error(
                'manual_qa_submit_failed',
                pipeline_id=argument.pipeline_id,
                error=str(exc),
            )
            return None

    def _do_work(self, argument: StepArgument) -> StepResult:
        submission = argument.stores.get('qa_submission')
        if submission is None:
            raise QaSubmissionTimeoutError(
                f'manual QA submission missing for pipeline {argument.pipeline_id}'
            )

        logger.info('qa_submission_received', pipeline_id=argument.pipeline_id)
        return StepResult(
            success=True,
            updates_to_stores={'reviewed_transcript_text': submission.get('reviewed_text', '')},
        )
