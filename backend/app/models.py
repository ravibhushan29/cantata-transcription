import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PipelineStatus(str, enum.Enum):
    WAITING = 'WAITING'
    RUNNING = 'RUNNING'
    COMPLETED = 'COMPLETED'
    CRASHED = 'CRASHED'
    CANCELLED = 'CANCELLED'


class StepStatus(str, enum.Enum):
    WAITING = 'WAITING'
    ENQUEUED = 'ENQUEUED'
    PROCESSING = 'PROCESSING'
    COMPLETED = 'COMPLETED'
    CRASHED = 'CRASHED'
    SKIPPED = 'SKIPPED'


class StepTag(str, enum.Enum):
    STT_SUBMIT = 'STT_SUBMIT'
    STT_CALLBACK_INGEST = 'STT_CALLBACK_INGEST'
    AUTO_QA_INVITE = 'AUTO_QA_INVITE'
    MANUAL_QA_SUBMIT = 'MANUAL_QA_SUBMIT'
    DELIVERY = 'DELIVERY'


PIPELINE_STEP_ORDER: list[StepTag] = [
    StepTag.STT_SUBMIT,
    StepTag.STT_CALLBACK_INGEST,
    StepTag.AUTO_QA_INVITE,
    StepTag.MANUAL_QA_SUBMIT,
    StepTag.DELIVERY,
]


class Record(Base):
    """Single-table archive for aged-out DLQ rows per AGENTS.md polymorphism convention."""

    __tablename__ = 'record'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Pipeline(Base):
    __tablename__ = 'pipeline'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audio_url: Mapped[str] = mapped_column(String, nullable=False)
    customer_webhook_url: Mapped[str] = mapped_column(String, nullable=False)
    editor_email: Mapped[str] = mapped_column(String, nullable=False)

    status: Mapped[str] = mapped_column(
        String, nullable=False, default=PipelineStatus.WAITING.value, index=True
    )
    current_step: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    steps_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    stores_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    is_pipeline_level_crash: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exception: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
