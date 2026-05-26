# HK Life Pilot Runbook

This runbook describes the local end-to-end pilot path for importing the reusable HK life fixture into SQLite, running the FastAPI service, and smoke-testing the API contract used by `ai_interface`.

## Fixture

Reusable candidate bundle:

```text
tests/fixtures/hk_life_pilot/candidate.json
```

The fixture uses `life_product_extractor` schema version `0.1` and contains:

- project-ready Hong Kong life data for two products;
- one insurer passed at import time;
- three evidence-backed source documents; and
- one unsupported document recorded in ingestion metadata.

## Import into local SQLite

From the repository root:

```bash
python -m postgres_api.import_extractor \
  tests/fixtures/hk_life_pilot/candidate.json \
  --database-url "sqlite+pysqlite:///hk_life_pilot.db" \
  --project-slug hk-life \
  --project-name "HK Life Pilot" \
  --insurer-name "Harbour Assurance Limited" \
  --create-tables
```

Expected summary fields include:

```json
{
  "status": "ok",
  "products_seen": 2,
  "products_created": 2,
  "versions_created": 2,
  "source_documents_created": 3,
  "evidence_spans_created": 3,
  "unsupported_documents": 1,
  "warnings": []
}
```

Re-running the same command is safe for catalog rows: products, versions, and source documents are upserted by stable keys while a new ingestion run records each import attempt.

## Run the API against the pilot DB

```bash
DATABASE_URL="sqlite+pysqlite:///hk_life_pilot.db" \
uvicorn postgres_api.main:app --reload
```

The API listens at `http://127.0.0.1:8000` by default.

## Smoke curl endpoints

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/client-config
curl http://127.0.0.1:8000/projects
curl 'http://127.0.0.1:8000/products?project_slug=hk-life'
curl 'http://127.0.0.1:8000/source-documents?project_slug=hk-life&limit=10'
curl 'http://127.0.0.1:8000/exports/products.json?project_slug=hk-life'
```

To inspect one product in detail, copy an `id` from the products response:

```bash
PRODUCT_ID=<id-from-products-response>
curl "http://127.0.0.1:8000/products/${PRODUCT_ID}"
```

Review task smoke flow:

```bash
PRODUCT_ID=<id-from-products-response>

curl -X POST http://127.0.0.1:8000/review-tasks \
  -H 'content-type: application/json' \
  -d "{\"project_slug\":\"hk-life\",\"subject_type\":\"product\",\"subject_id\":\"${PRODUCT_ID}\",\"notes\":\"Validate pilot extraction before advisor demo\",\"priority\":7}"

REVIEW_TASK_ID=<id-from-review-task-create-response>

curl -X PATCH "http://127.0.0.1:8000/review-tasks/${REVIEW_TASK_ID}" \
  -H 'content-type: application/json' \
  -d '{"status":"in_progress","notes":"Assigned to reviewer","priority":4}'

curl 'http://127.0.0.1:8000/review-tasks?project_slug=hk-life&status=in_progress'
```

## ai_interface integration notes

- Use `GET /client-config` at startup to discover paths, review statuses, and feature flags.
- Use `GET /projects`, then call `GET /products?project_slug=hk-life` to populate catalog views.
- Fetch details via `GET /products/{id}` and supporting evidence via `GET /source-documents?project_slug=hk-life`.
- Use `GET /exports/products.json?project_slug=hk-life` for a compact product export payload.
- Only call `POST /review-tasks` and `PATCH /review-tasks/{id}` from UI flows that intentionally perform review writes.
- For browser development, set `CORS_ORIGINS` to explicit frontend origins, for example `CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`.

Authentication is still out of scope for this service; do not expose write endpoints publicly without gateway or application-layer auth.

## Acceptance checklist

- [ ] Import command exits successfully and prints `"status": "ok"`.
- [ ] Import summary reports 2 products, 2 versions, 3 source documents, 3 evidence spans, and 1 unsupported document.
- [ ] `GET /client-config` returns paths for products, source documents, exports, and review tasks.
- [ ] `GET /projects` includes `hk-life` / `HK Life Pilot`.
- [ ] `GET /products?project_slug=hk-life` returns both pilot products.
- [ ] `GET /products/{id}` returns latest metadata summary and evidence IDs.
- [ ] `GET /source-documents?project_slug=hk-life` returns three evidence-backed documents.
- [ ] `GET /exports/products.json?project_slug=hk-life` returns `count: 2`.
- [ ] Review task create, update, and filtered list calls succeed.
- [ ] `python -m ruff check .` and `python -m pytest` pass.

## Cleanup

Stop `uvicorn`, then remove the local SQLite files:

```bash
rm -f hk_life_pilot.db hk_life_pilot.db-shm hk_life_pilot.db-wal
```
