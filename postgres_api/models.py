from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from postgres_api.db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_slug", "slug", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    ingestion_runs: Mapped[list["IngestionRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    source_documents: Mapped[list["SourceDocument"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    review_tasks: Mapped[list["ReviewTask"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    hk_life_products: Mapped[list["HKLifeProduct"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class IngestionRun(TimestampMixin, Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    source: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    run_metadata: Mapped[dict | None] = mapped_column(JSON)

    project: Mapped[Project] = relationship(back_populates="ingestion_runs")
    source_documents: Mapped[list["SourceDocument"]] = relationship(back_populates="ingestion_run", passive_deletes=True)
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="ingestion_run", passive_deletes=True)


class SourceDocument(TimestampMixin, Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("project_id", "url", name="uq_source_documents_project_url"),
        UniqueConstraint("project_id", "sha256", name="uq_source_documents_project_sha256"),
        CheckConstraint("url IS NOT NULL OR sha256 IS NOT NULL", name="ck_source_documents_url_or_sha256"),
        Index("ix_source_documents_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="SET NULL"))
    url: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(500))
    content_type: Mapped[str | None] = mapped_column(String(120))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_metadata: Mapped[dict | None] = mapped_column(JSON)

    project: Mapped[Project] = relationship(back_populates="source_documents")
    ingestion_run: Mapped[IngestionRun | None] = relationship(back_populates="source_documents")
    evidence_spans: Mapped[list["EvidenceSpan"]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan", passive_deletes=True
    )


class Artifact(TimestampMixin, Base):
    __tablename__ = "artifacts"
    __table_args__ = (Index("ix_artifacts_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="SET NULL"))
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_metadata: Mapped[dict | None] = mapped_column(JSON)

    project: Mapped[Project] = relationship(back_populates="artifacts")
    ingestion_run: Mapped[IngestionRun | None] = relationship(back_populates="artifacts")


class EvidenceSpan(TimestampMixin, Base):
    __tablename__ = "evidence_spans"
    __table_args__ = (Index("ix_evidence_spans_source_document_id", "source_document_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False
    )
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    selector: Mapped[dict | None] = mapped_column(JSON)

    source_document: Mapped[SourceDocument] = relationship(back_populates="evidence_spans")


class ReviewTask(TimestampMixin, Base):
    __tablename__ = "review_tasks"
    __table_args__ = (Index("ix_review_tasks_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(120), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="review_tasks")


class HKInsurer(TimestampMixin, Base):
    __tablename__ = "hk_insurers"
    __table_args__ = (
        UniqueConstraint("canonical_name", name="uq_hk_insurers_canonical_name"),
        UniqueConstraint("ia_code", name="uq_hk_insurers_ia_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ia_code: Mapped[str | None] = mapped_column(String(80))
    website_url: Mapped[str | None] = mapped_column(Text)

    products: Mapped[list["HKLifeProduct"]] = relationship(
        back_populates="insurer", cascade="all, delete-orphan", passive_deletes=True
    )


class HKLifeProduct(TimestampMixin, Base):
    __tablename__ = "hk_life_products"
    __table_args__ = (
        UniqueConstraint("insurer_id", "canonical_name", name="uq_hk_life_products_insurer_name"),
        Index("ix_hk_life_products_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    insurer_id: Mapped[int] = mapped_column(ForeignKey("hk_insurers.id", ondelete="CASCADE"), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_type: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")

    project: Mapped[Project] = relationship(back_populates="hk_life_products")
    insurer: Mapped[HKInsurer] = relationship(back_populates="products")
    versions: Mapped[list["HKLifeProductVersion"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", passive_deletes=True
    )
    aliases: Mapped[list["HKLifeProductAlias"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", passive_deletes=True
    )


class HKLifeProductVersion(TimestampMixin, Base):
    __tablename__ = "hk_life_product_versions"
    __table_args__ = (
        UniqueConstraint("product_id", "version_label", name="uq_hk_life_product_versions_label"),
        Index("ix_hk_life_product_versions_product_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("hk_life_products.id", ondelete="CASCADE"), nullable=False
    )
    version_label: Mapped[str] = mapped_column(String(120), nullable=False)
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    product_metadata: Mapped[dict | None] = mapped_column(JSON)

    product: Mapped[HKLifeProduct] = relationship(back_populates="versions")


class HKLifeProductAlias(TimestampMixin, Base):
    __tablename__ = "hk_life_product_aliases"
    __table_args__ = (UniqueConstraint("product_id", "alias", name="uq_hk_life_product_aliases"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("hk_life_products.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    locale: Mapped[str | None] = mapped_column(String(20))

    product: Mapped[HKLifeProduct] = relationship(back_populates="aliases")
