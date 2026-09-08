# ADR 002: Dead-Letter Queue Persistence

Status: Accepted — 2025-11-18. Author: Jen Wei. Related: [ADR-001](001_pipeline_design.md), [ADR-003](003_retry_policy.md).

## Context

The December 2024 STT outage left a chunk of transcripts in `CRASHED` state with their underlying Dramatiq messages stuck in `dramatiq:default.XQ`. On-call had no way to list the failed messages, no link from a CRASHED pipeline row back to the Dramatiq message that failed it, and no replay path. The post-mortem recommended persisting dead-lettered messages to Postgres with a stable link to the originating pipeline.

## Decision

Introduce a `dead_letter_messages` table with the following schema:

```sql
CREATE TABLE dead_letter_messages (
    id              UUID PRIMARY KEY,
    pipeline_id     UUID NOT NULL REFERENCES pipeline(id),
    step_tag        TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    failure_class   TEXT NOT NULL CHECK (failure_class IN ('TRANSIENT','POISON','NEEDS_HUMAN','UNKNOWN')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_retry_at   TIMESTAMPTZ,
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    replayed_at     TIMESTAMPTZ
);

CREATE INDEX ix_dlq_pipeline_id ON dead_letter_messages(pipeline_id);
CREATE INDEX ix_dlq_failure_class ON dead_letter_messages(failure_class) WHERE replayed_at IS NULL;
```

Archival hooks into Dramatiq's `after_nack` middleware so every dead-lettered message is written to the table atomically with the step's CRASHED status update on the parent pipeline.

Replay is exposed via `POST /dlq/{id}/replay`. The replay endpoint:

1. Verifies the failure class is in `{TRANSIENT, UNKNOWN}`. POISON and NEEDS_HUMAN classes require explicit operator discard or a human action before replay is offered.
2. Re-enqueues the original payload to the same Dramatiq actor.
3. Sets `replayed_at = now()` on the DLQ row.

The Redis `XQ` set is no longer the source of truth — it's a transient buffer.

## Consequences

- Operators get a queryable, paginated list of failed messages via `GET /dlq`.
- Replays are recorded and auditable.
- The `dead_letter_messages` table grows unbounded; retention is handled by a separate nightly job that archives rows older than 90 days to cold storage.
- A reconciler (`app/dlq/reconciler.py`) sweeps for orphaned `CRASHED` pipelines whose Dramatiq message landed in Redis but never made it to the table (the rare double-fault path).
