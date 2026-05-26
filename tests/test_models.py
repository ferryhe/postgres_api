import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from postgres_api.db import Base
from postgres_api.models import (
    Artifact,
    EvidenceSpan,
    HKInsurer,
    HKLifeProduct,
    HKLifeProductAlias,
    HKLifeProductVersion,
    IngestionRun,
    Project,
    ReviewTask,
    SourceDocument,
)


def test_model_crud_smoke_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(slug="hk-life", name="HK Life")
        insurer = HKInsurer(canonical_name="Example Life Insurance", ia_code="IA-EX")
        product = HKLifeProduct(
            project=project,
            insurer=insurer,
            canonical_name="Example Whole Life",
            product_type="whole_life",
        )
        product.versions.append(HKLifeProductVersion(version_label="2026-01", summary="Initial"))
        product.aliases.append(HKLifeProductAlias(alias="Example WL", locale="en-HK"))
        source = SourceDocument(
            project=project,
            url="https://example.test/product.pdf",
            sha256="a" * 64,
            title="Product brochure",
        )
        session.add_all([project, insurer, product, source])
        session.commit()

        loaded = session.scalar(select(HKLifeProduct).where(HKLifeProduct.canonical_name == "Example Whole Life"))

        assert loaded is not None
        assert loaded.insurer.canonical_name == "Example Life Insurance"
        assert loaded.aliases[0].alias == "Example WL"


def test_project_delete_cascades_owned_children_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(slug="cascade", name="Cascade")
        ingestion_run = IngestionRun(project=project, status="completed")
        source = SourceDocument(project=project, ingestion_run=ingestion_run, url="https://example.test/doc")
        source.evidence_spans.append(EvidenceSpan(quote="quoted evidence"))
        artifact = Artifact(project=project, ingestion_run=ingestion_run, artifact_type="snapshot", uri="s3://bucket/key")
        review_task = ReviewTask(project=project, subject_type="document", subject_id="1")
        insurer = HKInsurer(canonical_name="Cascade Life")
        product = HKLifeProduct(project=project, insurer=insurer, canonical_name="Cascade Product")
        product.versions.append(HKLifeProductVersion(version_label="v1"))
        product.aliases.append(HKLifeProductAlias(alias="Cascade Alias"))

        session.add_all([project, ingestion_run, source, artifact, review_task, insurer, product])
        session.commit()
        project_id = project.id

    with Session(engine) as session:
        project = session.get(Project, project_id)
        assert project is not None
        session.delete(project)
        session.commit()

    with Session(engine) as session:
        for model in (
            Project,
            IngestionRun,
            SourceDocument,
            EvidenceSpan,
            Artifact,
            ReviewTask,
            HKLifeProduct,
            HKLifeProductVersion,
            HKLifeProductAlias,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0

        assert session.scalar(select(func.count()).select_from(HKInsurer)) == 1


def test_source_document_requires_url_or_sha256_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(slug="source-check", name="Source Check")
        session.add(SourceDocument(project=project))

        with pytest.raises(IntegrityError):
            session.commit()
