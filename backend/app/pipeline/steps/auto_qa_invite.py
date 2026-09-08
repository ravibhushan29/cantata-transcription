"""AUTO_QA_INVITE: mint a signed Magic Link and email it to the assigned QA editor via SMTP."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from app.config import settings
from app.models import StepTag
from app.observability.logging import logger
from app.pipeline.base_step import BaseStep, StepArgument, StepResult


class SmtpTransientError(RuntimeError):
    pass


def _mint_magic_link(pipeline_id: str, editor_email: str) -> str:
    nonce = secrets.token_urlsafe(24)
    body = f'{pipeline_id}:{editor_email}:{nonce}'.encode()
    sig = hmac.new(settings.magic_link_signing_secret.encode(), body, hashlib.sha256).hexdigest()
    return f'https://cantata.example.test/qa?nonce={nonce}&sig={sig}'


def _send_email(to_address: str, link: str) -> None:
    """Stub SMTP. In a real deployment this would call the SMTP gateway."""
    force_mode = os.environ.get('FAKE_SMTP_FAILURE_MODE', '')
    if force_mode == 'transient_5xx':
        raise SmtpTransientError('SMTP gateway returned 521')
    logger.info('smtp_send_ok', to=to_address, link=link)


class StepAutoQaInvite(BaseStep):
    tag = StepTag.AUTO_QA_INVITE
    is_triggered_outside = False

    def run(self, argument: StepArgument) -> StepResult | None:
        try:
            link = _mint_magic_link(argument.pipeline_id, argument.editor_email)
            logger.info(
                'magic_link_minted',
                pipeline_id=argument.pipeline_id,
                editor_email=argument.editor_email,
            )
            _send_email(argument.editor_email, link)
            return StepResult(success=True, updates_to_stores={'last_magic_link': link})
        except Exception as exc:
            logger.error('auto_qa_invite_failed', pipeline_id=argument.pipeline_id, error=str(exc))
            return None
