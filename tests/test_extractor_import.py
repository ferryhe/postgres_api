import json
import subprocess
import sys
from copy import deepcopy

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


def test_shared_evidence_id_is_preserved_per_product_without_duplicate_span() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    bundle = minimal_candidate_bundle()
    second_product = deepcopy(bundle["products"][0])
    second_product["product_id"] = "prod-2"
    second_product["product_identity"]["product_name"] = "Example Term Life"
    bundle["products"].append(second_product)

    with Session(engine, expire_on_commit=False) as session:
        summary = import_extractor_bundle(
            session,
            bundle,
            project_slug="hk-life",
            project_name="HK Life",
            insurer_name="Manulife",
        )

        assert summary.products_created == 2
        assert summary.evidence_spans_created == 1
        assert summary.evidence_spans_reused == 1

    with Session(engine) as session:
        versions = session.scalars(select(HKLifeProductVersion).order_by(HKLifeProductVersion.version_label)).all()
        assert [version.product_metadata["evidence_ids"] for version in versions] == [["ev-1"], ["ev-1"]]
        assert [version.product_metadata["source_ids"] for version in versions] == [["source-1"], ["source-1"]]
        assert session.scalar(select(func.count()).select_from(EvidenceSpan)) == 1


def test_idless_evidence_entries_for_same_document_are_preserved() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    bundle = minimal_candidate_bundle()
    first_evidence = bundle["products"][0]["evidence"][0]
    first_evidence.pop("id")
    second_evidence = deepcopy(first_evidence)
    second_evidence.update(
        {
            "line_start": 12,
            "line_end": 13,
            "span_start": 126,
            "span_end": 150,
            "source_quote": "A separate id-less evidence quote.",
        }
    )
    bundle["products"][0]["evidence"].append(second_evidence)

    with Session(engine, expire_on_commit=False) as session:
        summary = import_extractor_bundle(
            session,
            bundle,
            project_slug="hk-life",
            project_name="HK Life",
            insurer_name="Manulife",
        )

        assert summary.source_documents_created == 1
        assert summary.evidence_spans_created == 2

    with Session(engine) as session:
        document = session.scalar(select(SourceDocument))
        assert document is not None
        evidence_metadata = document.document_metadata["evidence"]
        assert len(evidence_metadata) == 2
        assert [item["id"] for item in evidence_metadata] == [None, None]
        assert [item["source_quote"] for item in evidence_metadata] == [
            "Surrender charges may apply.",
            "A separate id-less evidence quote.",
        ]

        version = session.scalar(select(HKLifeProductVersion))
        assert version is not None
        assert len(version.product_metadata["evidence_ids"]) == 2
        assert len(set(version.product_metadata["evidence_ids"])) == 2


def test_same_insurer_and_product_name_can_exist_in_multiple_projects() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        first = import_extractor_bundle(
            session,
            minimal_candidate_bundle(),
            project_slug="project-one",
            project_name="Project One",
            insurer_name="Manulife",
        )
        first_product_id = session.scalar(select(HKLifeProduct.id).where(HKLifeProduct.project_id == first.project_id))

    with Session(engine, expire_on_commit=False) as session:
        second = import_extractor_bundle(
            session,
            minimal_candidate_bundle(),
            project_slug="project-two",
            project_name="Project Two",
            insurer_name="Manulife",
        )

    with Session(engine) as session:
        products = session.scalars(select(HKLifeProduct).order_by(HKLifeProduct.project_id)).all()
        assert len(products) == 2
        assert first_product_id is not None
        assert products[0].id == first_product_id
        assert products[0].project_id == first.project_id
        assert products[1].project_id == second.project_id
        assert products[0].canonical_name == products[1].canonical_name == "Example Whole Life"


def test_synthetic_source_document_url_escapes_components_to_avoid_collisions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    first_bundle = minimal_candidate_bundle()
    first_bundle["fixture_set_id"] = "fixture/a"
    first_bundle["products"][0]["evidence"][0]["document_id"] = "doc-1"

    second_bundle = minimal_candidate_bundle()
    second_bundle["fixture_set_id"] = "fixture"
    second_bundle["products"][0]["evidence"][0]["id"] = "ev-2"
    second_bundle["products"][0]["evidence"][0]["document_id"] = "a/doc-1"

    with Session(engine, expire_on_commit=False) as session:
        import_extractor_bundle(
            session,
            first_bundle,
            project_slug="hk-life",
            project_name="HK Life",
            insurer_name="Manulife",
        )
        import_extractor_bundle(
            session,
            second_bundle,
            project_slug="hk-life",
            project_name="HK Life",
            insurer_name="Manulife",
        )

    with Session(engine) as session:
        urls = session.scalars(select(SourceDocument.url).order_by(SourceDocument.url)).all()
        assert urls == ["extractor://fixture%2Fa/doc-1", "extractor://fixture/a%2Fdoc-1"]
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 2
