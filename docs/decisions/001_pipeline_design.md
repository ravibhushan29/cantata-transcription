# ADR 001: Pipeline State Machine

## Status

Accepted — 2025-09-04 — Platform team

## Context

We needed a way to model multi-step transcription workflows where each step may be synchronous, asynchronous, or externally triggered (human-in-the-loop). The state of an in-flight order needed to be inspectable from the admin tooling and recoverable after process restarts.

We considered:

- Pure dramatiq actor chaining (each actor sends the next), with no central state.
- A workflow framework (Temporal, Prefect).
- A hand-rolled state machine backed by a Postgres row with a JSONB `steps_state` blob.

## Decision

We adopted the hand-rolled state machine. Each transcription order is a `Pipeline` row. The orchestrator advances the pipeline through a fixed ordered list of step tags. Each step's status lives in `steps_state[step_tag]`, and a separate `stores_state` JSONB blob carries data between steps.

Each step is implemented as a class deriving from `BaseStep`, returning a `StepResult`. The orchestrator dispatches each step to dramatiq, commits status transitions in two phases, and halts the pipeline on a step crash.

## Consequences

- No external workflow dependency.
- Schema migrations are easy because the per-step shape lives in JSONB.
- The two-phase commit protocol means orphaned pipelines (status committed, next-step dispatch never happened) need a reconciler — accepted as a known follow-up.
- Step-class polymorphism keeps step behaviour close to its data.
