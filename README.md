# postgres_api

FastAPI service skeleton for a Postgres-backed product catalog and evidence ingestion workflow.

## PR1 scope

This initial skeleton includes:

- FastAPI app with `GET /health` returning service metadata.
- SQLAlchemy 2.x model definitions for the core ingestion tables and Hong Kong life product domain tables.
- Alembic migration `0001_initial_schema` for a Postgres-ready schema.
- Pytest coverage for `/health`, SQLite model CRUD smoke, and Alembic upgrade on SQLite.
- GitHub Actions CI for linting and tests.

Import/extraction APIs are intentionally out of scope for PR1.

## Schema overview

Core tables:

- `projects`
- `ingestion_runs`
- `source_documents`
- `artifacts`
- `evidence_spans`
- `review_tasks`

HK life domain tables:

- `hk_insurers`
- `hk_life_products`
- `hk_life_product_versions`
- `hk_life_product_aliases`

Idempotency and lookup constraints include unique project slugs, insurer canonical names and IA codes, source document `project_id + url` / `project_id + sha256`, product `insurer_id + canonical_name`, product version labels, and product aliases.

## Local development

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Run the API:

```bash
uvicorn postgres_api.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok","service":"postgres_api","version":"0.1.0"}
```

## Database and migrations

Production is expected to use PostgreSQL via SQLAlchemy's psycopg driver:

```bash
export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/postgres_api"
alembic upgrade head
```

Tests run migrations against SQLite to keep CI lightweight. The schema uses portable SQLAlchemy types (`Integer`, `String`, `Text`, `JSON`, timezone-aware `DateTime`) and avoids Postgres-only features in PR1 so the initial Alembic migration can be smoke-tested on SQLite as well as applied to Postgres.

## Testing

```bash
ruff check .
pytest
```
