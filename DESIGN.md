# DESIGN.md — Cantata DLQ Assessment

## Summary

Complete DLQ implementation: broker-level retries, XQ + `pipeline.steps_state` archival, failure classification, operator replay, reconciler, auto-retry scheduler, retention, and Prometheus metrics. Follows `backend/AGENTS.md` (Redis XQ, embedded JSONB, catch-and-return-None steps).

## Which failures belong in the DLQ?

| Step | Failure kind | Class | DLQ? | Replay? |
|------|-------------|-------|------|---------|
| STT_SUBMIT | Vendor 5xx, connection drop | TRANSIENT | Yes (after retries exhausted) | Yes |
| STT_CALLBACK_INGEST | Malformed payload | POISON | Yes | No — discard + ticket |
| STT_CALLBACK_INGEST | Missing callback payload | Soft fail | Yes (embedded) | No |
| AUTO_QA_INVITE | SMTP 5xx | TRANSIENT | Yes | Yes |
| MANUAL_QA_SUBMIT | Editor timeout / missing submission | NEEDS_HUMAN | Yes | No — contact editor first |
| DELIVERY | Customer webhook 5xx | TRANSIENT | Yes | Yes |

**Not all failures are the same.** Steps return `None` (hard failure) or `StepResult(success=False)` (soft failure). The orchestrator classifies and either schedules an auto-retry (`next_retry_at` in `steps_state.retry`) or archives to `steps_state.dlq`. Dramatiq XQ + `after_nack` middleware covers the safety-net path for uncaught raises.

## Replay safety

`POST /dlq/{id}/replay`:

1. Looks up entry in XQ and/or embedded `steps_state.dlq`.
2. **Blocks** replay when `failure_class ∈ {POISON, NEEDS_HUMAN}` (409).
3. Re-enqueues via `run_step.send` with pipeline/step from the archived payload.
4. Sets `replayed_at` on the pipeline row and resets step to ENQUEUED.

Steps are idempotent per AGENTS.md — no pre-flight dedupe check.

## Operator workflow (3am)

1. `GET /pipelines/{id}` — check `status == CRASHED`.
2. `GET /dlq?pipelineId={id}` — find DLQ row with `failure_class`, `attempts`, exception.
3. Check `pendingRetries` for auto-retry schedule.
4. If `TRANSIENT` or `UNKNOWN`: `POST /dlq/{message_id}/replay`.
5. If `POISON`: `DELETE /dlq/{id}`, open ticket.
6. If `NEEDS_HUMAN`: contact QA editor, then discard.
7. `GET /metrics` — alert on `cantata_dlq_size > 25`.
8. `POST /dlq/reconcile` — sweep XQ → Postgres embed if archival missed.

## What was built

### Core DLQ spine
- `app/broker.py` — Retries (5×, 1s→256s) + `DLQArchivalMiddleware`
- `app/dlq/classifier.py` — step-aware failure classification
- `app/dlq/archive.py` — embed DLQ, schedule retry, list pending
- `app/dlq/middleware.py` — `after_nack` → archive
- `app/dlq/service.py` — XQ + embedded listing, replay guards
- `app/dlq/retry.py` — backoff schedule

### Completed “next steps”
- `app/dlq/reconciler.py` — XQ entries missing from `steps_state` → embed
- `app/dlq/scheduler.py` + `app/dlq/tasks.py` — auto-retry due entries
- `app/dlq/retention.py` — archive DLQ blobs >90 days to `record` table
- `app/models.py` — `Record` polymorphic archive table + migration
- `GET /metrics` — Prometheus `cantata_dlq_size`, embedded/pending gauges
- `POST /dlq/reconcile`, `POST /dlq/retention/run`
- `scripts/dlq_scheduler.py` + `scheduler` compose service
- Docker compose profiles: `failure-stt`, `failure-smtp`, `failure-delivery`
- All five steps migrated to catch-and-return-None per AGENTS.md
- STT callback uses `model_construct` per vendor SLA convention

## Architecture

```
Step.run() → None | StepResult
     ↓
Orchestrator
  ├─ TRANSIENT + retries left → schedule_retry (next_retry_at)
  └─ else → embed_dlq (CRASHED)

Scheduler (every 30s) → dispatch due retries
Reconciler → XQ ⊄ steps_state → embed
Retention → steps_state.dlq > 90d → record table
```

## Assumptions documented

1. **AGENTS.md vs ADR-002** — followed AGENTS.md (embedded JSONB, no `dead_letter_messages` table).
2. **Retry ownership** — orchestrator owns step retries via scheduler; dramatiq retries are safety-net only.
3. **Retention** — uses polymorphic `record` table per AGENTS.md; replayed entries are not purged.
4. **Failure compose profiles** — stop default `worker` when using a profile worker to avoid duplicate consumers.

## Tradeoffs

- **Embedded JSONB** — simple, matches AGENTS.md; production would add GIN index on `steps_state`.
- **Scheduler polling** — 30s interval vs event-driven; adequate for assessment scale.
- **Uniform retry budget** — POISON messages still get orchestrator retries before DLQ (could short-circuit by step in future).
