# On-Call Runbook — Cantata Transcription

Owner: SRE. Last touched 2026-04-30. Linked: [architecture.md](architecture.md), [ADR-002](decisions/002_dlq_persistence.md), [ADR-003](decisions/003_retry_policy.md).

(TODO: sections on stuck-in-WAITING and customer-webhook backpressure are still missing — write up after the next drill.)

## Triage Flow

When a pipeline is reported as stuck or failing, follow this sequence:

### 1. Check pipeline status

```bash
curl http://localhost:8000/pipelines/{pipeline_id}
```

If `status == "CRASHED"` and `is_pipeline_level_crash == true`, the step exceeded its retry budget and the message has been dead-lettered.

### 2. Inspect the DLQ entry

```bash
curl http://localhost:8000/dlq?pipelineId={pipeline_id}
```

This returns the dead-letter row for this pipeline, including `failure_class`, `attempts`, and the original payload.

### 3. Replay

For `failure_class in {TRANSIENT, UNKNOWN}`:

```bash
curl -X POST http://localhost:8000/dlq/{dlq_id}/replay
```

This re-enqueues the original message to the same Dramatiq actor. Replay is safe — all pipeline steps are idempotent (see [AGENTS.md](../backend/AGENTS.md) for the architectural rationale).

For `failure_class == POISON`, do not replay. Discard the row and create a Linear ticket for the platform team to investigate the parsing error.

For `failure_class == NEEDS_HUMAN`, contact the assigned QA editor before replay.

## Step-Specific Notes

### STT_SUBMIT

Replays are safe. The STT vendor deduplicates submitted jobs by audio hash server-side — repeated calls to `submit_job(audio_url=...)` for the same audio return the same `job_id`, so there is no risk of double-billing.

### STT_CALLBACK_INGEST

Failures here are almost always POISON — a malformed payload from the vendor. Do not replay. Discard and ticket.

### AUTO_QA_INVITE

Replays are safe. SMTP failures are transient and the invite system is idempotent.

### MANUAL_QA_SUBMIT

If the step crashed, the editor missed their SLA. Contact the editor; if they cannot complete the work, reassign via the admin tool, then mark the DLQ row as `NEEDS_HUMAN` and discard.

### DELIVERY

Replays are safe. Customer webhooks are idempotent on the customer side per our integration agreement.

## Metrics

The DLQ size is exposed at `GET /dlq` and as a Prometheus gauge `cantata_dlq_size`. Alert thresholds:

| Threshold | Severity |
|-----------|----------|
| > 5       | INFO     |
| > 25      | WARN     |
| > 100     | PAGE     |
