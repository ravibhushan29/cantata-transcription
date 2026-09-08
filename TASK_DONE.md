# TASK_DONE.md — Cantata Transcription DLQ Assessment

**Repo:** https://github.com/ravibhushan29/cantata-transcription

---

## 1. Problem Statement

Cantata Transcription runs a 5-step async pipeline (STT → callback → QA invite → manual QA → delivery). When steps failed in production:

- Pipelines went to `CRASHED` with **no visible failed work**
- On-call had **no list of dead-lettered messages**
- There was **no replay path** and **no guidance on retry safety**

**Goal:** Design and implement a durable Dead-Letter Queue (DLQ) with operator-facing APIs, safe replay, and observability.

---

## 2. What Was Broken Before

| Issue | Before |
|-------|--------|
| Dramatiq retries | `max_retries=0` on the step actor — immediate failure, no backoff |
| Exception handling | Orchestrator swallowed or re-raised inconsistently |
| DLQ visibility | XQ listing read wrong Redis format — always returned empty |
| Pipeline link | No link from failed message → `pipeline_id` |
| Failure types | No classification (transient vs poison vs human) |
| Replay | No safety checks; actor not registered in API process |
| Archival | `after_nack` middleware had wrong signature — never ran |
| Retention / reconcile | Not implemented |

---

## 3. What Was Built (End-to-End)

### High-level flow

```
Pipeline step fails
       ↓
Step returns None or StepResult(success=False)   ← no raise into dramatiq (AGENTS.md)
       ↓
Orchestrator classifies failure
       ├─ TRANSIENT + retries left → schedule_retry (next_retry_at in steps_state)
       └─ retries exhausted / POISON / NEEDS_HUMAN → embed_dlq (CRASHED)

Scheduler (every 10s) dispatches due auto-retries
Dramatiq after_nack (safety net) → embed_dlq from XQ
Reconciler → XQ entries missing from Postgres → embed
Operator → GET /dlq → POST /dlq/{id}/replay (if safe)
Retention → DLQ blobs older than 90 days → record archive table
```

### Failure classification

| Step | Typical failure | Class | Auto-retry? | Manual replay? |
|------|-----------------|-------|-------------|----------------|
| STT_SUBMIT | Vendor 503 | TRANSIENT | Yes (5× backoff) | Yes |
| STT_CALLBACK_INGEST | Bad payload | POISON | No | No (409) |
| AUTO_QA_INVITE | SMTP 521 | TRANSIENT | Yes | Yes |
| MANUAL_QA_SUBMIT | Missing QA submission | NEEDS_HUMAN | No | No (409) |
| DELIVERY | Webhook 503 | TRANSIENT | Yes | Yes |

---

## 4. Files Added / Changed

### New files

| File | Purpose |
|------|---------|
| `backend/app/broker.py` | Shared Dramatiq broker — 5 retries, exponential backoff, DLQ middleware |
| `backend/app/dlq/classifier.py` | Maps step + error → `TRANSIENT` / `POISON` / `NEEDS_HUMAN` / `UNKNOWN` |
| `backend/app/dlq/archive.py` | Embed DLQ in `pipeline.steps_state`, schedule retries, list pending |
| `backend/app/dlq/middleware.py` | `after_nack` → persist to Postgres when Dramatiq dead-letters |
| `backend/app/dlq/retry.py` | Backoff schedule: 1s, 4s, 16s, 64s, 256s |
| `backend/app/dlq/reconciler.py` | Sync XQ messages missing from `steps_state` |
| `backend/app/dlq/scheduler.py` | Dispatch steps whose `next_retry_at` has passed |
| `backend/app/dlq/retention.py` | Archive DLQ rows >90 days to `record` table |
| `backend/app/dlq/tasks.py` | Dramatiq maintenance actor (reconcile + retry + retention) |
| `backend/scripts/dlq_scheduler.py` | Enqueues maintenance tick every N seconds |
| `backend/alembic/versions/2026-09-08_record_archive.py` | Migration for `record` archive table |
| `DESIGN.md` | Design doc with tradeoffs and assumptions |
| `.gitignore` | Python, venv, env, IDE exclusions |

### Modified files

| File | Change |
|------|--------|
| `backend/app/pipeline/runner.py` | Removed `max_retries=0`; uses broker defaults |
| `backend/app/pipeline/orchestrator.py` | Handles `None`/soft failures; schedules retry or embeds DLQ |
| `backend/app/pipeline/base_step.py` | `run()` return type → `StepResult \| None` |
| `backend/app/pipeline/steps/*.py` | All 5 steps: catch-and-return-None per AGENTS.md |
| `backend/app/dlq/service.py` | Fixed XQ read (`XQ` + `XQ.msgs` hash); merged listing; replay guards |
| `backend/app/dlq/metrics.py` | Prometheus text format for `cantata_dlq_size` |
| `backend/app/api/routes/dlq.py` | Added reconcile, retention, `pipelineId` filter, `pendingRetries` |
| `backend/app/main.py` | `/metrics` endpoint; register actors for replay |
| `backend/app/models.py` | Added `Record` table for retention archive |
| `backend/app/config.py` | `dlq_max_retries`, `dlq_retention_days`, scheduler interval |
| `backend/docker-compose.yml` | Added `scheduler` + failure scenario profiles |

---

## 5. API Endpoints (Operator Surface)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dlq` | List DLQ entries + XQ gauges + `pendingRetries` |
| GET | `/dlq?pipelineId={id}` | Filter by pipeline |
| GET | `/dlq/{message_id}` | Single entry |
| POST | `/dlq/{message_id}/replay` | Re-enqueue (409 if POISON/NEEDS_HUMAN) |
| DELETE | `/dlq/{message_id}` | Discard XQ entry |
| POST | `/dlq/reconcile` | XQ → Postgres sync + run due auto-retries |
| POST | `/dlq/retention/run` | Archive entries older than 90 days |
| GET | `/metrics` | Prometheus: `cantata_dlq_size`, embedded/pending counts |
| GET | `/pipelines/{id}` | Pipeline status (existing) |

Swagger: http://localhost:8000/docs

---

## 6. How to Run

```bash
cd backend
docker compose up
```

Services: `api` (8000), `worker`, `scheduler`, `postgres`, `redis`

### Test a failure scenario

```bash
# Stop normal worker, start failure profile
docker compose stop worker
docker compose --profile failure-stt up -d worker-stt-failure

# Create a pipeline (via API or seed script)
curl -X POST http://localhost:8000/pipelines \
  -H 'Content-Type: application/json' \
  -d '{"audioUrl":"https://example.test/a.wav","customerWebhookUrl":"https://example.test/hook","editorEmail":"test@example.com"}'

# Watch DLQ
curl http://localhost:8000/dlq
curl http://localhost:8000/metrics
```

Profiles: `failure-stt`, `failure-smtp`, `failure-delivery`

---

## 7. E2E Tests Performed

| Test | Result |
|------|--------|
| Happy path: create → STT callback → QA submit → COMPLETED | Pass |
| GET `/dlq` lists XQ + embedded entries | Pass |
| GET `/metrics` exposes Prometheus gauges | Pass |
| POST `/dlq/reconcile` syncs XQ → Postgres | Pass |
| POST `/dlq/retention/run` runs without error | Pass |
| POISON failure → replay returns **409** | Pass |
| TRANSIENT failure → auto-retry increments attempt counter | Pass |
| TRANSIENT DLQ entry → replay → pipeline recovers | Pass |
| Full pipeline completion after DLQ replay | Pass |

---

## 8. Key Design Decisions (Easy Talking Points)

1. **No separate DLQ Postgres table** — followed `backend/AGENTS.md`; embedded DLQ metadata in `pipeline.steps_state` JSONB. Redis XQ is the message store; Postgres is the operator source of truth.

2. **Steps never raise into Dramatiq** — catch-and-return-`None`; orchestrator owns retry vs dead-letter routing. Avoids bypassing the state machine (root cause of past P1 incidents per AGENTS.md).

3. **Two retry layers:**
   - **Orchestrator scheduler** — primary path, 5× backoff, `next_retry_at` in JSONB
   - **Dramatiq broker retries** — safety net for unexpected raises; `after_nack` archives to Postgres

4. **Replay safety** — blocked for `POISON` and `NEEDS_HUMAN` (HTTP 409). Steps are idempotent — no dedupe header needed.

5. **Reconciler** — handles double-fault where XQ has a message but Postgres embed failed.

6. **Retention** — polymorphic `record` table per AGENTS.md; 90-day cutoff configurable.

---

## 9. Assumptions Made

| # | Assumption | Would ask in real interview |
|---|------------|----------------------------|
| 1 | AGENTS.md supersedes ADR-002's `dead_letter_messages` table | Is Postgres DLQ table still planned? |
| 2 | Orchestrator owns retries; Dramatiq retries are backup | Confirm retry ownership model |
| 3 | XQ + embedded JSONB is durable enough for ops | What is XQ TTL in prod? |
| 4 | 90-day retention to cold `record` table is sufficient | Where does cold storage live? |
| 5 | Failure compose profiles are acceptable for local testing | Is there a CI failure-test harness? |

---

## 10. 3-Minute Explanation Script

> "The pipeline had five async steps but when things failed, work disappeared — no DLQ list, no replay, no safety checks.
>
> I built an operator-facing DLQ spine: failures are classified (transient, poison, needs-human), transient ones get five auto-retries with exponential backoff, then land in a queryable DLQ linked to the pipeline row. Operators list failures via GET /dlq, check failure_class, and replay safe ones with POST /dlq/id/replay — poison messages are blocked with a 409.
>
> I followed the repo's AGENTS.md — no separate DLQ table, metadata embedded in pipeline JSONB, steps catch exceptions and return None so the orchestrator controls routing. I also added a reconciler for XQ/Postgres drift, a scheduler for auto-retries, retention for 90-day archives, and Prometheus metrics for alerting.
>
> Tradeoff: embedded JSONB is simple and matches team conventions, but at scale you'd want a GIN index or materialized view for DLQ queries."

---

## 11. Related Docs

- `DESIGN.md` — detailed design and tradeoffs
- `backend.md` — original assessment brief
- `docs/runbook.md` — on-call triage flow
- `backend/AGENTS.md` — coding standards followed
