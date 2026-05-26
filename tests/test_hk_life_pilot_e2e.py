import json
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from postgres_api.db import Base, get_session
from postgres_api.main import app
from postgres_api.models import EvidenceSpan, HKInsurer, HKLifeProduct, IngestionRun, Project, SourceDocument

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hk_life_pilot" / "candidate.json"


def test_hk_life_pilot_import_and_api_acceptance(tmp_path) -> None:
    db_path = tmp_path / "hk_life_pilot.db"
    database_url = f"sqlite+pysqlite:///{db_path}"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "postgres_api.import_extractor",
            str(FIXTURE_PATH),
            "--database-url",
            database_url,
            "--project-slug",
            "hk-life",
            "--project-name",
            "HK Life Pilot",
            "--insurer-name",
            "Harbour Assurance Limited",
            "--create-tables",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    assert summary["status"] == "ok"
    assert summary["products_seen"] == 2
    assert summary["products_created"] == 2
    assert summary["versions_created"] == 2
    assert summary["source_documents_created"] == 3
    assert summary["evidence_spans_created"] == 3
    assert summary["unsupported_documents"] == 1
    assert summary["warnings"] == []

    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    try:
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Project)) == 1
            assert session.scalar(select(func.count()).select_from(HKInsurer)) == 1
            assert session.scalar(select(func.count()).select_from(HKLifeProduct)) == 2
            assert session.scalar(select(func.count()).select_from(SourceDocument)) == 3
            assert session.scalar(select(func.count()).select_from(EvidenceSpan)) == 3
            run = session.scalar(select(IngestionRun))
            assert run is not None
            assert run.run_metadata["fixture_set_id"] == "hk-life-pilot-2026-05"
            assert run.run_metadata["unsupported_documents"][0]["document_id"] == "hk-tax-general-faq.pdf"

        def override_get_session() -> Generator[Session, None, None]:
            with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        try:
            client = TestClient(app)

            config_response = client.get("/client-config")
            assert config_response.status_code == 200
            assert config_response.json()["paths"]["products"] == "/products"

            projects_response = client.get("/projects")
            assert projects_response.status_code == 200
            projects = projects_response.json()
            assert [(project["slug"], project["name"]) for project in projects] == [("hk-life", "HK Life Pilot")]

            products_response = client.get("/products", params={"project_slug": "hk-life"})
            assert products_response.status_code == 200
            products = products_response.json()
            assert [product["canonical_name"] for product in products] == [
                "Golden Lotus Life Protect Elite",
                "Harbour Term Choice",
            ]
            assert {product["product_type"] for product in products} == {"whole_life", "term_life"}
            assert all(product["insurer"]["canonical_name"] == "Harbour Assurance Limited" for product in products)
            assert all(product["version_count"] == 1 for product in products)

            first_product_id = products[0]["id"]
            detail_response = client.get(f"/products/{first_product_id}")
            assert detail_response.status_code == 200
            detail = detail_response.json()
            assert detail["canonical_name"] == "Golden Lotus Life Protect Elite"
            assert detail["versions"][0]["version_label"] == "hk-life-pilot-2026-05:gl-life-protect-elite:v0.1"
            assert detail["latest_metadata_summary"] == {"decrements": 1, "benefits": 1, "explicit_unknowns": 1}
            assert detail["latest_evidence_ids"] == ["gl-ev-1", "gl-ev-2"]

            documents_response = client.get("/source-documents", params={"project_slug": "hk-life", "limit": 10})
            assert documents_response.status_code == 200
            documents = documents_response.json()
            assert len(documents) == 3
            assert [document["document_metadata"]["document_id"] for document in documents] == [
                "gl-life-protect-elite-brochure.pdf",
                "gl-life-protect-elite-policy.pdf",
                "harbour-term-choice-brochure.pdf",
            ]

            export_response = client.get("/exports/products.json", params={"project_slug": "hk-life"})
            assert export_response.status_code == 200
            export = export_response.json()
            assert export["count"] == 2
            assert export["products"][1]["versions"][0]["source_document_ids"] == [
                "harbour-term-choice-brochure.pdf"
            ]

            create_response = client.post(
                "/review-tasks",
                json={
                    "project_slug": "hk-life",
                    "subject_type": "product",
                    "subject_id": str(first_product_id),
                    "notes": "Validate pilot extraction before advisor demo",
                    "priority": 7,
                },
            )
            assert create_response.status_code == 201
            created_task = create_response.json()
            assert created_task["status"] == "open"
            assert created_task["priority"] == 7

            update_response = client.patch(
                f"/review-tasks/{created_task['id']}",
                json={"status": "in_progress", "notes": "Assigned to reviewer", "priority": 4},
            )
            assert update_response.status_code == 200
            updated_task = update_response.json()
            assert updated_task["status"] == "in_progress"
            assert updated_task["notes"] == "Assigned to reviewer"
            assert updated_task["priority"] == 4

            list_tasks_response = client.get(
                "/review-tasks", params={"project_slug": "hk-life", "status": "in_progress"}
            )
            assert list_tasks_response.status_code == 200
            assert [task["id"] for task in list_tasks_response.json()] == [created_task["id"]]
        finally:
            app.dependency_overrides.clear()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
