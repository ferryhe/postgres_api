from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from postgres_api.db import Base, get_session
from postgres_api.extractor_import import import_extractor_bundle
from postgres_api.main import app
from postgres_api.models import Artifact, HKLifeProduct, HKLifeProductAlias, IngestionRun, Project


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with Session(engine, expire_on_commit=False) as session:
        import_extractor_bundle(
            session,
            _minimal_candidate_bundle(),
            project_slug="hk-life",
            project_name="HK Life",
            insurer_name="Manulife",
        )
        product = session.scalar(select(HKLifeProduct))
        assert product is not None
        project = session.scalar(select(Project).where(Project.slug == "hk-life"))
        assert project is not None
        ingestion_run = session.scalar(select(IngestionRun).where(IngestionRun.project_id == project.id))
        assert ingestion_run is not None
        session.add(HKLifeProductAlias(product=product, alias="Example WL", locale="en-HK"))
        session.add(Artifact(project=project, ingestion_run=ingestion_run, artifact_type="fixture", uri="artifact://fixture-a"))
        session.commit()

    def override_get_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _minimal_candidate_bundle() -> dict:
    return {
        "schema_version": "0.1",
        "fixture_set_id": "fixture-a",
        "summary": {"documents": 1, "products": 1},
        "products": [
            {
                "product_id": "prod-1",
                "product_identity": {
                    "product_name": "Example Whole Life",
                    "jurisdiction": "HK",
                    "product_class_primary": "whole_life",
                },
                "source_document_ids": ["doc-1"],
                "paired_source_scenario_ids": ["scenario-1"],
                "decrements": [{"id": "dec-1", "label": "surrender charge", "evidence_refs": ["ev-1"]}],
                "benefits": [],
                "explicit_unknowns": [],
                "evidence": [
                    {
                        "id": "ev-1",
                        "source_id": "source-1",
                        "document_id": "doc-1",
                        "section_id": "sec-1",
                        "span_start": 100,
                        "span_end": 125,
                        "source_quote": "Surrender charges may apply.",
                    }
                ],
            }
        ],
    }


def test_list_products_after_importer(client: TestClient) -> None:
    response = client.get("/products", params={"project_slug": "hk-life"})

    assert response.status_code == 200
    products = response.json()
    assert len(products) == 1
    assert products[0]["canonical_name"] == "Example Whole Life"
    assert products[0]["project"]["slug"] == "hk-life"
    assert products[0]["insurer"]["canonical_name"] == "Manulife"
    assert products[0]["product_type"] == "whole_life"
    assert products[0]["status"] == "active"
    assert products[0]["version_count"] == 1
    assert products[0]["latest_version_label"] == "fixture-a:prod-1:v0.1"


def test_list_products_pagination(client: TestClient) -> None:
    response = client.get("/products", params={"project_slug": "hk-life", "limit": 1, "offset": 1})

    assert response.status_code == 200
    assert response.json() == []

    invalid_response = client.get("/products", params={"limit": 101})
    assert invalid_response.status_code == 422


def test_product_detail_includes_versions_aliases_and_latest_metadata(client: TestClient) -> None:
    product_id = client.get("/products").json()[0]["id"]

    response = client.get(f"/products/{product_id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["aliases"] == [{"id": detail["aliases"][0]["id"], "alias": "Example WL", "locale": "en-HK"}]
    assert detail["versions"][0]["version_label"] == "fixture-a:prod-1:v0.1"
    assert detail["versions"][0]["evidence_ids"] == ["ev-1"]
    assert detail["latest_metadata_summary"] == {"decrements": 1, "benefits": 0, "explicit_unknowns": 0}
    assert detail["latest_evidence_ids"] == ["ev-1"]


def test_source_documents_list(client: TestClient) -> None:
    response = client.get("/source-documents", params={"project_slug": "hk-life", "limit": 10})

    assert response.status_code == 200
    documents = response.json()
    assert len(documents) == 1
    assert documents[0]["url"] == "extractor://fixture-a/doc-1"
    assert documents[0]["document_metadata"]["evidence"][0]["id"] == "ev-1"


def test_create_and_update_review_task(client: TestClient) -> None:
    project = client.get("/projects").json()[0]
    create_response = client.post(
        "/review-tasks",
        json={
            "project_slug": project["slug"],
            "subject_type": "product",
            "subject_id": "1",
            "notes": "Needs actuarial review",
            "priority": 5,
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["status"] == "open"
    assert created["priority"] == 5

    list_response = client.get("/review-tasks", params={"project_slug": "hk-life", "status": "open"})
    assert list_response.status_code == 200
    assert [task["id"] for task in list_response.json()] == [created["id"]]

    update_response = client.patch(
        f"/review-tasks/{created['id']}",
        json={"status": "closed", "notes": "Reviewed", "priority": 1},
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["status"] == "closed"
    assert updated["notes"] == "Reviewed"
    assert updated["priority"] == 1


def test_export_products_json(client: TestClient) -> None:
    response = client.get("/exports/products.json", params={"project_slug": "hk-life"})

    assert response.status_code == 200
    export = response.json()
    assert export["count"] == 1
    product = export["products"][0]
    assert product["canonical_name"] == "Example Whole Life"
    assert product["versions"][0]["product_metadata"]["raw_product"]["product_id"] == "prod-1"
    assert product["versions"][0]["source_document_ids"] == ["doc-1"]


def test_create_review_task_accepts_project_id(client: TestClient) -> None:
    project_id = client.get("/projects").json()[0]["id"]

    response = client.post(
        "/review-tasks",
        json={"project_id": project_id, "subject_type": "source_document", "subject_id": "1"},
    )

    assert response.status_code == 201
    assert response.json()["project"]["id"] == project_id


def test_create_review_task_validates_supported_subjects(client: TestClient) -> None:
    project = client.get("/projects").json()[0]
    products = client.get("/products", params={"project_slug": project["slug"]}).json()
    source_documents = client.get("/source-documents", params={"project_slug": project["slug"]}).json()

    for subject_type, subject_id in (
        ("product", products[0]["id"]),
        ("source_document", source_documents[0]["id"]),
        ("ingestion_run", 1),
        ("artifact", 1),
    ):
        response = client.post(
            "/review-tasks",
            json={"project_slug": project["slug"], "subject_type": subject_type, "subject_id": str(subject_id)},
        )
        assert response.status_code == 201
        assert response.json()["subject_id"] == str(subject_id)


def test_create_review_task_rejects_invalid_subjects(client: TestClient) -> None:
    project = client.get("/projects").json()[0]

    unsupported_response = client.post(
        "/review-tasks",
        json={"project_slug": project["slug"], "subject_type": "document", "subject_id": "1"},
    )
    assert unsupported_response.status_code == 400
    assert unsupported_response.json()["detail"] == "unsupported subject_type"

    non_integer_response = client.post(
        "/review-tasks",
        json={"project_slug": project["slug"], "subject_type": "product", "subject_id": "prod-1"},
    )
    assert non_integer_response.status_code == 400
    assert non_integer_response.json()["detail"] == "subject_id must be an integer"

    missing_response = client.post(
        "/review-tasks",
        json={"project_slug": project["slug"], "subject_type": "product", "subject_id": "999"},
    )
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "subject not found in project"


def test_review_task_input_validation(client: TestClient) -> None:
    project = client.get("/projects").json()[0]
    base_payload = {"project_slug": project["slug"], "subject_type": "product", "subject_id": "1"}

    extra_response = client.post("/review-tasks", json={**base_payload, "unexpected": True})
    assert extra_response.status_code == 422

    invalid_status_response = client.post("/review-tasks", json={**base_payload, "status": "pending"})
    assert invalid_status_response.status_code == 422

    invalid_priority_response = client.post("/review-tasks", json={**base_payload, "priority": 101})
    assert invalid_priority_response.status_code == 422


def test_create_review_task_requires_project(client: TestClient) -> None:
    response = client.post("/review-tasks", json={"subject_type": "product", "subject_id": "1"})

    assert response.status_code == 400
    assert response.json()["detail"] == "project_slug or project_id is required"
