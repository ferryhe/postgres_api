import json
import subprocess
import sys

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from postgres_api.db import Base
from postgres_api.extractor_import import import_extractor_bundle
from postgres_api.models import (
    EvidenceSpan,
    HKInsurer,
    HKLifeProduct,
    HKLifeProductVersion,
    IngestionRun,
    Project,
    SourceDocument,
)


def minimal_candidate_bundle() -> dict:
    return {
        "schema_version": "0.1",
        "fixture_set_id": "fixture-a",
        "summary": {"documents": 1, "products": 1},
        "unsupported_documents": [{"document_id": "ignored.pdf", "reason": "not life"}],
        "products": [
            {
                "product_id": "prod-1",
                "product_identity": {
                    "product_name": "Example Whole Life",
                    "jurisdiction": "HK",
                    "product_class_primary": "whole_life",
                    "product_class_secondary": ["participating"],
                },
                "source_document_ids": ["doc-1"],
                "paired_source_scenario_ids": ["scenario-1"],
                "decrements": [
                    {
                        "id": "dec-1",
                        "label": "surrender charge",
                        "evidence_refs": ["ev-1"],
                        "confidence": 0.91,
                        "review_status": "candidate",
                    }
                ],
                "benefits": [],
                "explicit_unknowns": [],
                "evidence": [
                    {
                        "id": "ev-1",
                        "source_id": "source-1",
                        "document_id": "doc-1",
                        "section_id": "sec-1",
                        "line_start": 10,
                        "line_end": 11,
                        "span_start": 100,
                        "span_end": 125,
                        "source_quote": "Surrender charges may apply.",
                    }
                ],
            }
        ],
    }


def test_import_minimal_candidate_bundle_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        first = import_extractor_bundle(
            session,
            minimal_candidate_bundle(),
            project_slug="hk-life",
            project_name="HK Life",
            insurer_name="Manulife",
        )

        assert first.products_seen == 1
        assert first.products_created == 1
        assert first.versions_created == 1
        assert first.source_documents_created == 1
        assert first.evidence_spans_created == 1
        assert first.unsupported_documents == 1

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(HKInsurer)) == 1
        assert session.scalar(select(func.count()).select_from(HKLifeProduct)) == 1
        assert session.scalar(select(func.count()).select_from(HKLifeProductVersion)) == 1
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 1
        assert session.scalar(select(func.count()).select_from(EvidenceSpan)) == 1
        assert session.scalar(select(func.count()).select_from(IngestionRun)) == 1

        version = session.scalar(select(HKLifeProductVersion))
        assert version is not None
        assert version.version_label == "fixture-a:prod-1:v0.1"
        assert version.product_metadata["findings_summary"] == {
            "decrements": 1,
            "benefits": 0,
            "explicit_unknowns": 0,
        }
        assert version.product_metadata["evidence_ids"] == ["ev-1"]

        document = session.scalar(select(SourceDocument))
        assert document is not None
        assert document.url == "extractor://fixture-a/doc-1"
        assert document.sha256 is not None and len(document.sha256) == 64
        assert document.document_metadata["evidence"][0]["id"] == "ev-1"

    with Session(engine, expire_on_commit=False) as session:
        second = import_extractor_bundle(
            session,
            minimal_candidate_bundle(),
            project_slug="hk-life",
            project_name="HK Life",
            insurer_name="Manulife",
        )

        assert second.products_created == 0
        assert second.products_updated == 1
        assert second.versions_created == 0
        assert second.versions_updated == 1
        assert second.source_documents_created == 0
        assert second.evidence_spans_created == 0
        assert second.evidence_spans_reused == 1

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(HKInsurer)) == 1
        assert session.scalar(select(func.count()).select_from(HKLifeProduct)) == 1
        assert session.scalar(select(func.count()).select_from(HKLifeProductVersion)) == 1
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 1
        assert session.scalar(select(func.count()).select_from(EvidenceSpan)) == 1
        assert session.scalar(select(func.count()).select_from(IngestionRun)) == 2


def test_import_extractor_cli_outputs_summary(tmp_path) -> None:
    db_path = tmp_path / "extractor.db"
    bundle_path = tmp_path / "candidate.json"
    bundle_path.write_text(json.dumps(minimal_candidate_bundle()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "postgres_api.import_extractor",
            str(bundle_path),
            "--database-url",
            f"sqlite+pysqlite:///{db_path}",
            "--project-slug",
            "hk-life",
            "--project-name",
            "HK Life",
            "--insurer-name",
            "Manulife",
            "--create-tables",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    output = json.loads(completed.stdout)
    assert output["status"] == "ok"
    assert output["products_seen"] == 1
    assert output["versions_created"] == 1
    assert output["source_documents_created"] == 1
