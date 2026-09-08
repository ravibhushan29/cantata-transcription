# Development

## Docker Compose

Start the local stack:

```bash
cd backend
docker compose up
```

Services come up on:

- **Backend API:** <http://localhost:8000>
- **Swagger UI:** <http://localhost:8000/docs>
- **Postgres:** `localhost:5432` (db: `cantata`, user: `cantata`, password: `cantata`)
- **Redis:** `localhost:6379`

The `api` and `worker` services share the same image. The `worker` runs the dramatiq broker against Redis.

## Migrations

Migrations run automatically on `api` container startup. To run them manually against a local Python environment:

```bash
cd backend
uv sync
uv run alembic upgrade head
```

To create a new migration:

```bash
uv run alembic revision --autogenerate -m "your description"
```

## Seeding

To populate the database with five in-flight pipelines:

```bash
uv run python scripts/seed.py
```

## Tooling

- Python 3.12, `uv` for dependency management.
- `ruff` for lint + format.
- `pyright` (basic mode) for type checking — not strict, but no errors should be introduced.

## Logging

`structlog` is wired up at INFO. Step transitions and dramatiq message events log to stdout. There is no Sentry or Logfire backend in this assessment scaffold — what's here is what an on-call engineer would see in a real terminal.
