# Cantata Transcription — Architecture

Owner: Jen Wei. Originally written 2025-09-04, last touched 2026-04-12. Some sections pre-date ADR-002 and could use a refresh — flagged inline below.

Linked ADRs: [ADR-001](decisions/001_pipeline_design.md), [ADR-002](decisions/002_dlq_persistence.md), [ADR-003](decisions/003_retry_policy.md).

## Overview

Cantata Transcription is a pipeline-driven service. Each transcription order is represented by a single `Pipeline` row that progresses through five steps. The steps run as Dramatiq actors backed by Redis, with all durable state persisted to Postgres.

```
+-------------+    +---------------------+    +-----------------+
|  FastAPI    |--->|  Dramatiq broker    |--->|  Step actors    |
|  (api)      |    |  (Redis: default)   |    |  (worker)       |
+-------------+    +---------------------+    +-----------------+
        |                                              |
        v                                              v
   +-----------+                              +------------------+
   | Postgres  | <----------------------------|  Two-phase commit |
   | pipeline  |                              +------------------+
   +-----------+
```

## Pipeline State Machine

The `Pipeline` row holds:

- `status` ∈ {WAITING, RUNNING, COMPLETED, CRASHED, CANCELLED}
- `current_step` — the step tag currently being processed
- `steps_state` — JSONB blob keyed by step tag, holding per-step status + exception
- `stores_state` — JSONB blob for inter-step data sharing
- `is_pipeline_level_crash` — set when a step crash escalates to a pipeline halt

Transitions are committed in two phases:

1. Update the step's status (WAITING → ENQUEUED → PROCESSING → COMPLETED/CRASHED), commit.
2. Dispatch the next step's Dramatiq message, or park the pipeline if the next step is externally triggered.

Phase 1 is retried automatically by the platform if the DB commit fails transiently. Phase 2 is not retried — a reconciler picks up orphaned pipelines.

## Dead-Letter Queue

Failed Dramatiq messages are persisted to a Postgres table `dead_letter_messages`:

| Column                | Type             | Notes                                              |
|-----------------------|------------------|----------------------------------------------------|
| `id`                  | UUID             | Primary key                                        |
| `pipeline_id`         | UUID             | FK to `pipeline.id`                                |
| `step_tag`            | TEXT             | The step that failed                               |
| `message_id`          | TEXT             | Dramatiq message id                                |
| `payload`             | JSONB            | Full message body                                  |
| `failure_class`       | TEXT             | TRANSIENT \| POISON \| NEEDS_HUMAN \| UNKNOWN      |
| `attempts`            | INTEGER          | Number of dramatiq retry attempts before nack      |
| `next_retry_at`       | TIMESTAMPTZ      | When the message becomes eligible for auto-retry   |
| `archived_at`         | TIMESTAMPTZ      | When archival completed                            |
| `replayed_at`         | TIMESTAMPTZ      | Null until an operator replays via `POST /dlq/{id}/replay` |

Archival happens in a Dramatiq `after_nack` middleware, atomically with the step's CRASHED status update. The `GET /dlq` endpoint paginates over this table; `POST /dlq/{id}/replay` re-enqueues the message after verifying replay safety.

The Redis `XQ` set is treated as a transient buffer only — the Postgres table is the source of truth for any operator-visible DLQ state.

## Retries

All pipeline-step actors share a single retry policy configured at the broker level: 5 retries with exponential backoff (1s, 4s, 16s, 64s, 256s). After the fifth retry, the message is dead-lettered (see above). Individual actors do not override `max_retries`. Full rationale in [ADR-003](decisions/003_retry_policy.md).

## Observability

`structlog` is wired up at every layer with a fixed processor chain. Step transitions, broker enqueues, and DLQ archival events all emit structured logs. There is no Sentry or Logfire backend in the assessment scaffold.

## Vendor Boundary

The STT vendor's callback endpoints are signed with HMAC-SHA256. The callback handler parses the body with `model_construct` (not `model_validate`) because the vendor guarantees schema validity per their SLA — strict validation adds noise to traces.

Customer webhooks are fire-and-forget: we POST the final transcript, observe the response, and rely on the customer's own idempotency handling to deduplicate retries.
