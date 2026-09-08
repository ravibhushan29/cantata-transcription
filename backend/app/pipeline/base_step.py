from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.models import StepTag


@dataclass
class StepArgument:
    pipeline_id: str
    step_tag: StepTag
    audio_url: str
    customer_webhook_url: str
    editor_email: str
    stores: dict[str, Any]


@dataclass
class StepResult:
    success: bool
    updates_to_stores: dict[str, Any]
    error_message: str | None = None


class BaseStep(ABC):
    tag: StepTag
    is_triggered_outside: bool = False

    @abstractmethod
    def run(self, argument: StepArgument) -> StepResult | None: ...
