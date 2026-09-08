# ADR 003: Retry Policy

Status: Accepted — 2025-12-02. Author: Jen Wei. Related: [ADR-002](002_dlq_persistence.md).

## Context

Dramatiq's default retry policy (20 retries with up to 7 days between retries) is too aggressive for transcription work, where most transient failures resolve within seconds and a 7-day-old retry of a stale message can collide with operator state.

We need a uniform retry policy aligned to (a) the typical recovery time of our external dependencies (STT vendor, SMTP, customer webhook), and (b) the operator's tolerance for stuck pipelines.

## Decision

All pipeline-step Dramatiq actors share a single retry policy configured at the broker level:

- **Maximum retries**: 5
- **Backoff**: exponential, base 4 (delays of 1s, 4s, 16s, 64s, 256s)
- **After the fifth retry**: the message is dead-lettered (see [ADR 002](002_dlq_persistence.md)).

This is enforced by the broker configuration in `app/main.py`. Individual actors do not override `max_retries` or `min_backoff`.

## Consequences

- The longest a pipeline can spend in retry-purgatory is ~5 minutes.
- Transient external failures self-heal without operator action.
- Genuinely broken steps end up in the DLQ within minutes, not days.
- POISON failures (e.g. malformed STT callback payloads) still consume five retries before being archived — accepted as a minor cost in exchange for uniform policy.
