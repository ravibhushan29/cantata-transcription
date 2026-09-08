# Backend Lead Assessment: Pipeline Durability & Dead-Letter Queue

## Context

**Cantata Transcription** is our internal platform that turns customer-uploaded audio into reviewed, delivered transcripts. The work for each transcript moves through a five-step pipeline:

1. `STT_SUBMIT` — submit the audio to our speech-to-text vendor
2. `STT_CALLBACK_INGEST` — receive the vendor's callback, parse the transcript
3. `AUTO_QA_INVITE` — send a Magic Link invite to a QA editor
4. `MANUAL_QA_SUBMIT` — wait for the QA editor's submission (human-in-the-loop)
5. `DELIVERY` — push the finished transcript to the customer's webhook

Each step runs as a dramatiq actor against a Postgres-backed `Pipeline` row. The state machine, the actor wiring, and the five steps are already built. The repository under [backend/](backend/) is the full working service — `docker compose up` brings it online and a seed script under [backend/scripts/](backend/scripts/) creates in-flight pipelines to work against.

The service has been running internally for a few months. On-call is unhappy.

## The Problem

Steps fail in production. When a step crashes, the pipeline ends up in `CRASHED` state, and from the on-call engineer's perspective, **the work is just gone** — there's no list of failed messages, no way to retry, and no way to know whether retrying is even safe.

We need a durable dead-letter queue with a replay path, designed and partially implemented by you.

## Your Task

In ~90 minutes:

1. **Read the codebase.** Understand the pipeline state machine, the five steps, and what's already wired up around failure observability. Start at [backend/app/pipeline/](backend/app/pipeline/) and [backend/app/dlq/](backend/app/dlq/).
2. **Design it.** Write the design down in `DESIGN.md`. We'll especially want your answers to:
   - **Which failures belong in the DLQ?** Are all five steps' failures the same kind of problem? If not, how do you classify them?
   - **How does replay stay safe?** What does `POST /dlq/{id}/replay` actually do, and what guarantees does it need before it does it?
   - **How do you surface stuck or poison messages to on-call?** What's the operator workflow?
3. **Implement the spine.** You won't finish all of it. Pick what to build and what to leave as design notes — that prioritisation is part of what we're evaluating.

## What to send back

- `DESIGN.md` at the repo root — the design, with the tradeoffs you considered.
- Working code for the highest-value slice of that design.
- A short list of what you'd build next and what you cut.
- Any assumption you had to make that you could not verify from this repo, and what you'd have asked us.

## What we're evaluating

- Comfort with the existing pipeline architecture and the failure surface it exposes.
- Persistence design — schema, retention, indexes, links back to the pipeline.
- Observability — how does an operator find a stuck pipeline at 3am?
- Replay design — what does `POST /dlq/{id}/replay` actually do?
- Lead-shaped judgement — what did you cut, and why?

## Notes

- The existing repo is small but conventional. You should not need to rewrite anything that's already there to land your design — extending and integrating is fine.
- The [docs/](docs/) directory contains an architecture overview, a few ADRs from when the service was first built, and the current on-call runbook. They are part of the existing material.
- The repository's coding standards are in [backend/AGENTS.md](backend/AGENTS.md).
- Where something doesn't make sense, write the question down in `DESIGN.md` rather than guessing silently. The questions you'd have asked are part of what we read.
