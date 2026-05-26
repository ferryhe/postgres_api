from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewTaskStatus = Literal["open", "in_progress", "resolved", "rejected", "closed"]


class ProjectRead(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class NestedProject(BaseModel):
    id: int
    slug: str
    name: str


class NestedInsurer(BaseModel):
    id: int
    canonical_name: str
    ia_code: str | None = None
    website_url: str | None = None


class ProductListItem(BaseModel):
    id: int
    project: NestedProject
    insurer: NestedInsurer
    canonical_name: str
    product_type: str | None = None
    status: str
    version_count: int
    latest_version_label: str | None = None


class ProductVersionRead(BaseModel):
    id: int
    version_label: str
    effective_date: datetime | None = None
    summary: str | None = None
    product_metadata: dict[str, Any] | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProductAliasRead(BaseModel):
    id: int
    alias: str
    locale: str | None = None


class ProductDetail(ProductListItem):
    aliases: list[ProductAliasRead]
    versions: list[ProductVersionRead]
    latest_metadata_summary: dict[str, Any] | None = None
    latest_evidence_ids: list[str] = Field(default_factory=list)


class SourceDocumentRead(BaseModel):
    id: int
    project: NestedProject
    ingestion_run_id: int | None = None
    url: str | None = None
    sha256: str | None = None
    title: str | None = None
    content_type: str | None = None
    fetched_at: datetime | None = None
    document_metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ReviewTaskRead(BaseModel):
    id: int
    project: NestedProject
    subject_type: str
    subject_id: str
    status: str
    priority: int
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class ReviewTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: str
    subject_id: str
    notes: str | None = None
    priority: int = Field(default=0, ge=0, le=100)
    status: ReviewTaskStatus = "open"
    project_slug: str | None = None
    project_id: int | None = None


class ReviewTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReviewTaskStatus | None = None
    notes: str | None = None
    priority: int | None = Field(default=None, ge=0, le=100)


class ProductsExport(BaseModel):
    products: list[ProductDetail]
    count: int
