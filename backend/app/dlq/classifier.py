"""Failure classification for DLQ entries.

See docs/runbook.md for operator guidance per step.
"""

from __future__ import annotations

from app.models import StepTag

FAILURE_TRANSIENT = 'TRANSIENT'
FAILURE_POISON = 'POISON'
FAILURE_NEEDS_HUMAN = 'NEEDS_HUMAN'
FAILURE_UNKNOWN = 'UNKNOWN'

REPLAYABLE = {FAILURE_TRANSIENT, FAILURE_UNKNOWN}
NON_REPLAYABLE = {FAILURE_POISON, FAILURE_NEEDS_HUMAN}

_STEP_DEFAULTS: dict[str, str] = {
    StepTag.STT_SUBMIT.value: FAILURE_TRANSIENT,
    StepTag.STT_CALLBACK_INGEST.value: FAILURE_POISON,
    StepTag.AUTO_QA_INVITE.value: FAILURE_TRANSIENT,
    StepTag.MANUAL_QA_SUBMIT.value: FAILURE_NEEDS_HUMAN,
    StepTag.DELIVERY.value: FAILURE_TRANSIENT,
}


def classify(step_tag: str, *, exception_text: str = '') -> str:
    """Return failure_class for a dead-lettered step."""
    default = _STEP_DEFAULTS.get(step_tag, FAILURE_UNKNOWN)
    exc = exception_text.lower()

    if 'validation error' in exc or 'invalid payload' in exc or 'not a valid identifier' in exc:
        return FAILURE_POISON
    if 'manual qa submission missing' in exc or ('qa submission' in exc and 'missing' in exc):
        return FAILURE_NEEDS_HUMAN
    if '503' in exc or '521' in exc or '5xx' in exc or 'connection' in exc or 'timeout' in exc:
        return FAILURE_TRANSIENT

    return default


def replay_allowed(failure_class: str) -> bool:
    return failure_class in REPLAYABLE
