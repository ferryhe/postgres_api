# postgres_api

FastAPI service skeleton for a Postgres-backed product catalog and evidence ingestion workflow.

## PR1 scope

This initial skeleton includes:

- FastAPI app with `GET /health` returning service metadata.
- SQLAlchemy 2.x model definitions for the core ingestion tables and Hong Kong life product domain tables.
- Alembic migration `0001_initial_schema` for a Postgres-ready schema.
- Pytest coverage for `/health`, SQLite model CRUD smoke, and Alembic upgrade on SQLite.
- GitHub Actions CI for linting and tests.

Import/extraction APIs were intentionally out of scope for PR1. PR2 adds a CLI/service importer for `life_product_extractor` candidate and reviewed bundles; a FastAPI import endpoint remains intentionally deferred until service API requirements are clearer.

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

## Importing life_product_extractor bundles

PR2 imports `life_product_extractor` `candidate.json` or `reviewed.json` bundles with top-level `schema_version` `0.1` into the existing schema. The importer:

- upserts `projects` by slug, `hk_insurers` by canonical name, and `hk_life_products` by insurer + product name;
- creates one `ingestion_runs` row per import with bundle summary/review metadata;
- maps evidence documents to stable synthetic `source_documents` URLs like `extractor://{fixture_set_id}/{document_id}`;
- writes quotes to `evidence_spans`; and
- upserts product versions using labels like `{fixture_set_id}:{product_id}:v0.1`.

CLI usage:

```bash
python -m postgres_api.import_extractor path/to/candidate.json \
  --database-url "sqlite+pysqlite:///local.db" \
  --project-slug hk-life \
  --project-name "HK Life" \
  --insurer-name "Manulife"
```

For a fresh local SQLite smoke database, add `--create-tables`. Production databases should be migrated with Alembic instead. The installed console script equivalent is `import-extractor`.

The CLI prints a concise JSON summary with created/updated counts. A FastAPI endpoint is not included in PR2.

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
