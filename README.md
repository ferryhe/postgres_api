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

- upserts `projects` by slug, `hk_insurers` by canonical name, and `hk_life_products` by project + insurer + product name;
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

## HK life pilot fixture and runbook

PR5 adds a reusable end-to-end HK life pilot fixture at `tests/fixtures/hk_life_pilot/candidate.json`. It can be imported into local SQLite and exercised through the catalog, export, and review-task APIs. See `docs/hk_life_pilot_runbook.md` for the import command, API run command, smoke curl checks, `ai_interface` notes, acceptance checklist, and cleanup steps.

## Query, review, and export APIs

PR3 exposes DB-backed catalog APIs for downstream AI/review tooling. Authentication is intentionally not included yet.

Endpoints:

- `GET /projects` - list projects.
- `GET /products` - list HK life products. Optional query parameters: `project_slug`, `insurer_id`, `review_status` (maps to product `status`), `limit` (default `50`, max `100`), and `offset`. Each item includes project, insurer, canonical name, product type, status, version count, and latest version label.
- `GET /products/{product_id}` - product detail with aliases, versions, latest metadata summary, and latest evidence IDs.
- `GET /source-documents` - list source documents. Optional query parameters: `project_slug`, `limit` (default `100`, max `1000`), and `offset`.
- `GET /review-tasks` - list review tasks. Optional query parameters: `project_slug`, `status`, `limit` (default `100`, max `1000`), and `offset`.
- `POST /review-tasks` - create a review task. Body fields: `subject_type`, `subject_id`, optional `notes`, `priority` (default `0`, range `0..100`), `status` (default `open`), and either `project_slug` or `project_id`. Supported `subject_type` values are `product`, `source_document`, `ingestion_run`, and `artifact`; `subject_id` must be an integer ID for an existing row in the selected project. Extra request fields are rejected.
- `PATCH /review-tasks/{task_id}` - update review task `status`, `notes`, and/or `priority`. Valid statuses are `open`, `in_progress`, `resolved`, `rejected`, and `closed`; priority must be in `0..100`; extra request fields are rejected.
- `GET /exports/products.json` - export products as JSON for downstream consumers. Optional query parameters: `project_slug`, `limit` (default `100`, max `1000`), and `offset`.

Example review task creation:

```bash
curl -X POST http://127.0.0.1:8000/review-tasks \
  -H 'content-type: application/json' \
  -d '{"project_slug":"hk-life","subject_type":"product","subject_id":"1","notes":"Verify benefits","priority":5}'
```

Example product export:

```bash
curl 'http://127.0.0.1:8000/exports/products.json?project_slug=hk-life&limit=100&offset=0'
```

## ai_interface integration

This service includes a minimal contract for local `ai_interface` frontend integration without adding authentication or DB migrations.

- Base URL for local development: `http://127.0.0.1:8000`.
- Enable browser CORS only when needed by setting `CORS_ORIGINS` to a comma-separated allow-list of explicit `http://` or `https://` origins, for example `CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`. Wildcard (`*`), `null`, `file://`, and entries with paths, query strings, or fragments are rejected. When unset or empty, CORS middleware is not installed.
- OpenAPI schema for typed client generation: `GET /openapi.json`.
- Interactive API docs: `GET /docs`.
- Frontend bootstrap contract: `GET /client-config`, returning service/version metadata, stable paths, feature flags, and valid review task statuses.

Recommended ai_interface call sequence:

1. Call `GET /client-config` at startup to discover paths, feature availability, and enum values.
2. Optionally fetch `GET /openapi.json` during build/codegen to refresh a typed client.
3. List projects with `GET /projects`, then query products with `GET /products?project_slug=...`.
4. Fetch details with `GET /products/{product_id}` and supporting documents with `GET /source-documents?project_slug=...`.
5. Read review work via `GET /review-tasks?project_slug=...`; only call `POST /review-tasks` or `PATCH /review-tasks/{task_id}` from ai_interface flows that intentionally gate writes.

Authentication and authorization remain out of scope for this service. Browser-facing deployments should add auth at the gateway or application layer before exposing write endpoints.

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
