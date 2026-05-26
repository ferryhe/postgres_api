from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from postgres_api.db import Base, make_engine
from postgres_api.extractor_import import EXTRACTOR_SOURCE, ExtractorImportError, import_extractor_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import life_product_extractor candidate/reviewed JSON bundles.")
    parser.add_argument("bundle_path", type=Path, help="Path to candidate.json or reviewed.json")
    parser.add_argument("--database-url", required=True, help="SQLAlchemy database URL")
    parser.add_argument("--project-slug", required=True, help="Project slug to upsert")
    parser.add_argument("--project-name", help="Project display name; defaults to --project-slug")
    parser.add_argument("--insurer-name", required=True, help="HK insurer canonical name to upsert")
    parser.add_argument("--source-label", default=EXTRACTOR_SOURCE, help="IngestionRun.source value")
    parser.add_argument(
        "--create-tables",
        action="store_true",
        help="Create SQLAlchemy tables before import (intended for local SQLite smoke runs; use Alembic in production).",
    )
    args = parser.parse_args(argv)

    try:
        bundle = _load_bundle(args.bundle_path)
        engine = make_engine(args.database_url)
        if args.create_tables:
            Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        with session_factory() as session:
            summary = import_extractor_bundle(
                session,
                bundle,
                project_slug=args.project_slug,
                project_name=args.project_name,
                insurer_name=args.insurer_name,
                source_label=args.source_label,
            )
    except (OSError, json.JSONDecodeError, ExtractorImportError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 1

    print(json.dumps({"status": "ok", **summary.as_dict()}, sort_keys=True))
    return 0


def _load_bundle(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ExtractorImportError("bundle JSON must be an object")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
