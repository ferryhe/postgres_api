"""Initial Postgres-ready schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("ix_projects_slug", "projects", ["slug"], unique=True)

    op.create_table(
        "hk_insurers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("ia_code", sa.String(length=80), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        *timestamp_columns(),
        sa.UniqueConstraint("canonical_name", name="uq_hk_insurers_canonical_name"),
        sa.UniqueConstraint("ia_code", name="uq_hk_insurers_ia_code"),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("run_metadata", sa.JSON(), nullable=True),
        *timestamp_columns(),
    )

    op.create_table(
        "hk_life_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("insurer_id", sa.Integer(), sa.ForeignKey("hk_insurers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("product_type", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("insurer_id", "canonical_name", name="uq_hk_life_products_insurer_name"),
    )
    op.create_index("ix_hk_life_products_project_id", "hk_life_products", ["project_id"])

    op.create_table(
        "source_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), sa.ForeignKey("ingestion_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_metadata", sa.JSON(), nullable=True),
        *timestamp_columns(),
        sa.UniqueConstraint("project_id", "url", name="uq_source_documents_project_url"),
        sa.UniqueConstraint("project_id", "sha256", name="uq_source_documents_project_sha256"),
    )
    op.create_index("ix_source_documents_project_id", "source_documents", ["project_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), sa.ForeignKey("ingestion_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_metadata", sa.JSON(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])

    op.create_table(
        "evidence_spans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_document_id", sa.Integer(), sa.ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("selector", sa.JSON(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("ix_evidence_spans_source_document_id", "evidence_spans", ["source_document_id"])

    op.create_table(
        "review_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_type", sa.String(length=120), nullable=False),
        sa.Column("subject_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("ix_review_tasks_project_status", "review_tasks", ["project_id", "status"])

    op.create_table(
        "hk_life_product_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("hk_life_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_label", sa.String(length=120), nullable=False),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("product_metadata", sa.JSON(), nullable=True),
        *timestamp_columns(),
        sa.UniqueConstraint("product_id", "version_label", name="uq_hk_life_product_versions_label"),
    )
    op.create_index("ix_hk_life_product_versions_product_id", "hk_life_product_versions", ["product_id"])

    op.create_table(
        "hk_life_product_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("hk_life_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=True),
        *timestamp_columns(),
        sa.UniqueConstraint("product_id", "alias", name="uq_hk_life_product_aliases"),
    )


def downgrade() -> None:
    op.drop_table("hk_life_product_aliases")
    op.drop_index("ix_hk_life_product_versions_product_id", table_name="hk_life_product_versions")
    op.drop_table("hk_life_product_versions")
    op.drop_index("ix_review_tasks_project_status", table_name="review_tasks")
    op.drop_table("review_tasks")
    op.drop_index("ix_evidence_spans_source_document_id", table_name="evidence_spans")
    op.drop_table("evidence_spans")
    op.drop_index("ix_artifacts_project_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_source_documents_project_id", table_name="source_documents")
    op.drop_table("source_documents")
    op.drop_index("ix_hk_life_products_project_id", table_name="hk_life_products")
    op.drop_table("hk_life_products")
    op.drop_table("ingestion_runs")
    op.drop_table("hk_insurers")
    op.drop_index("ix_projects_slug", table_name="projects")
    op.drop_table("projects")
