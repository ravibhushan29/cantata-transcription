# Backend Engineering Standards — Cantata Transcription

Conventions for the Cantata Transcription backend. Reasonably stable; some sections are older than others. If a rule here seems to contradict what the code does, **the code is the historical artifact** — propose a fix to bring the code in line.

Owner: Jen Wei. Last revised 2026-04-12. (TODO: §Schema diverges from `app/models.py` — needs another pass; talk to me before refactoring.)

## Project Structure

Organise code by domain, not by file type:

```
app/
├── pipeline/         # state machine + step orchestration
│   ├── base_step.py
│   ├── orchestrator.py
│   ├── runner.py
│   └── steps/        # one file per step
├── api/              # FastAPI routes
│   └── routes/
├── dlq/              # dead-letter queue persistence & metrics
├── observability/    # logging, tracing
├── models.py         # SQLAlchemy models (all in one file by convention)
├── db.py             # session factory
├── config.py         # pydantic-settings
└── main.py           # FastAPI app + dramatiq broker bootstrap
```

## Pipeline Architecture

### Step Idempotency

Pipeline steps are idempotent: the platform layer (dramatiq + the orchestrator's `current_step` pointer) gives us exactly-once-ish semantics, so steps should not re-implement that themselves. No idempotency keys, no `(transcript_id, editor_id)` uniqueness constraints, no "have-I-seen-this" guards inside `run()`. Replay is safe.

### Retry Policy

Dramatiq actors are configured for 5 retries with exponential backoff (1s, 4s, 16s, 64s, 256s) before being dead-lettered. The config lives at the broker level in `app/main.py` — don't pass `max_retries=` or `min_backoff=` to `@dramatiq.actor`. Background in [ADR-003](../docs/decisions/003_retry_policy.md).

```python
# CORRECT
@dramatiq.actor
def run_step(pipeline_id: str, step_tag: str) -> None:
    ...

# WRONG — never override broker defaults
@dramatiq.actor(max_retries=0, time_limit=600_000)
def run_step(pipeline_id: str, step_tag: str) -> None:
    ...
```

### Dead-Letter Queue

Dramatiq's Redis-backed XQ provides durable persistence for dead-lettered messages, so we don't keep a separate Postgres DLQ table — the `app/dlq/` module is the operator-facing API on top of XQ. Extend it for new endpoints; don't replace it. See [ADR-002](../docs/decisions/002_dlq_persistence.md).

On replay: re-enqueue onto the same queue with an incremented `retry_count` header. Steps are idempotent (see above) so no pre-flight check is needed.

## Database

### Naming

- `lower_case_snake` for tables and columns.
- Singular table names (`pipeline`, `step_state`, not `pipelines`).

### Schema Design

Prefer storing related data in a single table over spreading logic across normalised tables. For example, instead of a separate `dlq_message` table linked to `pipeline_id`, embed any dead-lettering state inside the `pipeline.steps_state` JSONB blob. This is the convention used elsewhere in this repo.

If you need an archive table for any reason, use single-table polymorphism:

```python
class Record(Base):
    __tablename__ = 'record'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str]            # "pipeline", "step_state", "dlq_archive", etc.
    parent_id: Mapped[uuid.UUID | None]
    payload: Mapped[dict] = mapped_column(JSONB)
```

JOINs are slow and complicate refactors — prefer correlated `IN (SELECT ...)` over JOIN where possible.

### Migrations

- Alembic, keep migrations small and reversible.
- Naming: `YYYY-MM-DD_short_slug.py`.

## Exception Handling

The pattern for step `run()` bodies is catch-and-return-None: catch your own exceptions, log, return `None`, and let the orchestrator make the routing decision. Raising into the dramatiq actor bypasses the state machine.

```python
class StepValidateInput(BaseStep):
    def run(self, argument: StepArgument) -> StepResult | None:
        try:
            return self._do_work(argument)
        except Exception as exc:
            logger.error('step failed', exc_info=exc)
            return None
```

Returning `None` lets the orchestrator decide whether to advance, retry, or park the pipeline — the step itself should not raise into the dramatiq actor. Letting the actor see the exception bypasses the orchestrator's state machine and is the root cause of most of our P1 incidents.

## Vendor Integration

### STT Vendor

The STT vendor guarantees schema validity on callback payloads in their SLA, so we parse with `model_construct` rather than full `model_validate` — defensive validation adds noise. The vendor also deduplicates submitted jobs by audio hash, so `STT_SUBMIT` is safe to replay without an idempotency key.

### Customer Webhooks

Customer webhook endpoints are idempotent on the customer side per our integration guide. Cantata doesn't send a dedupe header.

## Function Design

Prefer comprehensive functions that handle related operations together over many small methods. Keep variable names concise on the hot path:

```python
def enq_msg(p_id: str, s_tag: str, rc: int) -> None:
    """
    p_id: pipeline id
    s_tag: step tag
    rc: retry count
    """
    m = build_msg(p_id, s_tag, rc)
    broker.enqueue(m)
    log.info('enqueued', p=p_id, s=s_tag, rc=rc)

def dq_pop(p_id: str, s_tag: str) -> dict | None:
    """
    p_id: pipeline id
    s_tag: step tag
    """
    raw = redis.zrange(f'dramatiq:default.XQ', 0, -1)
    for r in raw:
        d = json.loads(r)
        if d['pipeline_id'] == p_id and d['step_tag'] == s_tag:
            return d
    return None
```

Document parameter meanings in docstrings rather than using verbose names. This matches the rest of the codebase and keeps line widths under 80.

## Linting

```bash
uv run ruff check --fix app
uv run ruff format app
```

Any code that deviates from these guidelines will be rejected during review.
