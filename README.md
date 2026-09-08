# Backend Lead Assessment — Cantata Transcription

Thank you for your interest in the **Technical Backend Lead** role at **genieX**. This assessment is a take-home exercise based on a stripped-down version of one of our internal services.

Please read:

- **Task brief:** [backend.md](backend.md)
- **Setup:** [development.md](development.md)
- **Architecture & decisions:** [docs/architecture.md](docs/architecture.md), [docs/decisions/](docs/decisions/), [docs/runbook.md](docs/runbook.md)
- **Coding standards:** [backend/AGENTS.md](backend/AGENTS.md)

---

## Format

- **~90 minutes, on your own time.** We're asking for 90 minutes, not a weekend. Stop when the time is up and send us what you have.
- Use your editor, your machine, and an AI assistant of your choice (Claude Code, Copilot, Cursor — whatever you normally use). We expect you to lean on it the way you would on the job.
- **You are not expected to finish.** There is more design surface here than anyone can implement in 90 minutes. What matters is the design and the reasoning behind it. We'd suggest roughly 15 minutes reading, 25 designing, 45 building, 5 writing up — but that's your call to make.
- Afterwards we'll book 45 minutes to talk through what you built and what you didn't.

---

## What to send back

1. Your code — a patch, a branch, or a zip of the repo. Whatever's easiest.
2. **`DESIGN.md`** at the repo root. One page is plenty. Cover:
   - The design, and the tradeoffs you weighed.
   - What you built, what you deliberately cut, and what you'd do next.
   - **Any assumption you had to make that you couldn't verify from the repo** — and what you'd have asked us if we'd been on a call.

The write-up matters as much as the code. Bullet points are fine; we're not looking for prose.

---

## Setup

```bash
cd backend
docker compose up
```

- **API Documentation:** `http://localhost:8000/docs`
- **Backend API:** `http://localhost:8000`

See [development.md](development.md) for full setup including local Python and running migrations.

If you can't get it running, don't burn your 90 minutes on it — email us, and reason from the code in the meantime.

---

## What we're looking for

- Comfort reading an unfamiliar async/queue-based system at pace.
- Strong opinions on idempotency, durability, and replay safety.
- Clear prioritisation under a time budget — what you ship versus what you defer, and why.
- Engineering decisions written down. We care more about the reasoning than the line count.
