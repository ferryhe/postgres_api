from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from postgres_api.db import get_session
from postgres_api.models import (
    Artifact,
    HKLifeProduct,
    HKLifeProductVersion,
    IngestionRun,
    Project,
    ReviewTask,
    SourceDocument,
)
from postgres_api.schemas import (
    NestedInsurer,
    NestedProject,
    ProductAliasRead,
    ProductDetail,
    ProductListItem,
    ProductsExport,
    ProductVersionRead,
    ProjectRead,
    ReviewTaskCreate,
    ReviewTaskRead,
    ReviewTaskStatus,
    ReviewTaskUpdate,
    SourceDocumentRead,
)

router = APIRouter(tags=["catalog"])
SessionDep = Annotated[Session, Depends(get_session)]

SUPPORTED_REVIEW_SUBJECTS = {
    "product": HKLifeProduct,
    "source_document": SourceDocument,
    "ingestion_run": IngestionRun,
    "artifact": Artifact,
}


def _nested_project(project: Project) -> NestedProject:
    return NestedProject(id=project.id, slug=project.slug, name=project.name)


def _nested_insurer(product: HKLifeProduct) -> NestedInsurer:
    insurer = product.insurer
    return NestedInsurer(
        id=insurer.id,
        canonical_name=insurer.canonical_name,
        ia_code=insurer.ia_code,
        website_url=insurer.website_url,
    )


def _latest_version(product: HKLifeProduct) -> HKLifeProductVersion | None:
    if not product.versions:
        return None
    return max(
        product.versions,
        key=lambda version: (
            version.effective_date is not None,
            version.effective_date or version.created_at,
            version.id,
        ),
    )


def _product_list_item(product: HKLifeProduct) -> ProductListItem:
    latest = _latest_version(product)
    return ProductListItem(
        id=product.id,
        project=_nested_project(product.project),
        insurer=_nested_insurer(product),
        canonical_name=product.canonical_name,
        product_type=product.product_type,
        status=product.status,
        version_count=len(product.versions),
        latest_version_label=latest.version_label if latest else None,
    )


def _version_read(version: HKLifeProductVersion) -> ProductVersionRead:
    metadata = version.product_metadata or {}
    return ProductVersionRead(
        id=version.id,
        version_label=version.version_label,
        effective_date=version.effective_date,
        summary=version.summary,
        product_metadata=version.product_metadata,
        evidence_ids=list(metadata.get("evidence_ids") or []),
        source_document_ids=list(metadata.get("source_document_ids") or []),
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _product_detail(product: HKLifeProduct) -> ProductDetail:
    latest = _latest_version(product)
    latest_metadata: dict[str, Any] | None = latest.product_metadata if latest else None
    aliases = [
        ProductAliasRead(id=alias.id, alias=alias.alias, locale=alias.locale)
        for alias in sorted(product.aliases, key=lambda alias: alias.alias)
    ]
    versions = [
        _version_read(version)
        for version in sorted(product.versions, key=lambda version: (version.effective_date or version.created_at, version.id))
    ]
    return ProductDetail(
        **_product_list_item(product).model_dump(),
        aliases=aliases,
        versions=versions,
        latest_metadata_summary=latest_metadata.get("findings_summary") if latest_metadata else None,
        latest_evidence_ids=list(latest_metadata.get("evidence_ids") or []) if latest_metadata else [],
    )


def _source_document_read(document: SourceDocument) -> SourceDocumentRead:
    return SourceDocumentRead(
        id=document.id,
        project=_nested_project(document.project),
        ingestion_run_id=document.ingestion_run_id,
        url=document.url,
        sha256=document.sha256,
        title=document.title,
        content_type=document.content_type,
        fetched_at=document.fetched_at,
        document_metadata=document.document_metadata,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _review_task_read(task: ReviewTask) -> ReviewTaskRead:
    return ReviewTaskRead(
        id=task.id,
        project=_nested_project(task.project),
        subject_type=task.subject_type,
        subject_id=task.subject_id,
        status=task.status,
        priority=task.priority,
        notes=task.notes,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _get_project(session: Session, *, project_slug: str | None, project_id: int | None) -> Project:
    if project_id is None and project_slug is None:
        raise HTTPException(status_code=400, detail="project_slug or project_id is required")
    statement = select(Project)
    if project_id is not None:
        statement = statement.where(Project.id == project_id)
    if project_slug is not None:
        statement = statement.where(Project.slug == project_slug)
    project = session.scalar(statement)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _validate_review_subject(session: Session, *, project: Project, subject_type: str, subject_id: str) -> None:
    model = SUPPORTED_REVIEW_SUBJECTS.get(subject_type)
    if model is None:
        raise HTTPException(status_code=400, detail="unsupported subject_type")
    try:
        subject_pk = int(subject_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="subject_id must be an integer") from exc

    subject = session.scalar(select(model).where(model.id == subject_pk, model.project_id == project.id))
    if subject is None:
        raise HTTPException(status_code=404, detail="subject not found in project")


@router.get(
    "/projects",
    response_model=list[ProjectRead],
    summary="List projects",
    description="Return catalog projects ordered by slug.",
    operation_id="listProjects",
)
def list_projects(session: SessionDep) -> list[ProjectRead]:
    return list(session.scalars(select(Project).order_by(Project.slug)))


@router.get(
    "/products",
    response_model=list[ProductListItem],
    summary="List products",
    description="Return paginated HK life products with nested project, insurer, and latest-version summary fields.",
    operation_id="listProducts",
)
def list_products(
    session: SessionDep,
    project_slug: str | None = None,
    insurer_id: int | None = None,
    review_status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[ProductListItem]:
    statement = select(HKLifeProduct).options(
        selectinload(HKLifeProduct.project),
        selectinload(HKLifeProduct.insurer),
        selectinload(HKLifeProduct.versions),
    )
    if project_slug is not None:
        statement = statement.join(Project, HKLifeProduct.project_id == Project.id).where(Project.slug == project_slug)
    if insurer_id is not None:
        statement = statement.where(HKLifeProduct.insurer_id == insurer_id)
    if review_status is not None:
        statement = statement.where(HKLifeProduct.status == review_status)
    products = session.scalars(
        statement.order_by(HKLifeProduct.canonical_name, HKLifeProduct.id).offset(offset).limit(limit)
    ).all()
    return [_product_list_item(product) for product in products]


@router.get(
    "/products/{product_id}",
    response_model=ProductDetail,
    summary="Get product detail",
    description="Return one product with aliases, versions, latest metadata summary, and evidence IDs.",
    operation_id="getProduct",
)
def get_product(product_id: int, session: SessionDep) -> ProductDetail:
    product = session.scalar(
        select(HKLifeProduct)
        .where(HKLifeProduct.id == product_id)
        .options(
            selectinload(HKLifeProduct.project),
            selectinload(HKLifeProduct.insurer),
            selectinload(HKLifeProduct.versions),
            selectinload(HKLifeProduct.aliases),
        )
    )
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return _product_detail(product)


@router.get(
    "/source-documents",
    response_model=list[SourceDocumentRead],
    summary="List source documents",
    description="Return paginated source documents, optionally filtered by project slug.",
    operation_id="listSourceDocuments",
)
def list_source_documents(
    session: SessionDep,
    project_slug: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[SourceDocumentRead]:
    statement = select(SourceDocument).options(selectinload(SourceDocument.project))
    if project_slug is not None:
        statement = statement.join(Project, SourceDocument.project_id == Project.id).where(Project.slug == project_slug)
    documents = session.scalars(statement.order_by(SourceDocument.id).offset(offset).limit(limit)).all()
    return [_source_document_read(document) for document in documents]


@router.get(
    "/review-tasks",
    response_model=list[ReviewTaskRead],
    summary="List review tasks",
    description="Return paginated review tasks, optionally filtered by project slug and review status.",
    operation_id="listReviewTasks",
)
def list_review_tasks(
    session: SessionDep,
    project_slug: str | None = None,
    status: ReviewTaskStatus | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[ReviewTaskRead]:
    statement = select(ReviewTask).options(selectinload(ReviewTask.project))
    if project_slug is not None:
        statement = statement.join(Project, ReviewTask.project_id == Project.id).where(Project.slug == project_slug)
    if status is not None:
        statement = statement.where(ReviewTask.status == status)
    tasks = session.scalars(statement.order_by(ReviewTask.priority.desc(), ReviewTask.id).offset(offset).limit(limit)).all()
    return [_review_task_read(task) for task in tasks]


@router.post(
    "/review-tasks",
    response_model=ReviewTaskRead,
    status_code=201,
    summary="Create review task",
    description="Create a review task for a supported subject in a project. Authentication is not enforced by this service yet.",
    operation_id="createReviewTask",
)
def create_review_task(payload: ReviewTaskCreate, session: SessionDep) -> ReviewTaskRead:
    project = _get_project(session, project_slug=payload.project_slug, project_id=payload.project_id)
    _validate_review_subject(
        session,
        project=project,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
    )
    task = ReviewTask(
        project=project,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        status=payload.status,
        priority=payload.priority,
        notes=payload.notes,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return _review_task_read(task)


@router.patch(
    "/review-tasks/{task_id}",
    response_model=ReviewTaskRead,
    summary="Update review task",
    description="Update status, notes, or priority for an existing review task.",
    operation_id="updateReviewTask",
)
def update_review_task(task_id: int, payload: ReviewTaskUpdate, session: SessionDep) -> ReviewTaskRead:
    task = session.scalar(select(ReviewTask).where(ReviewTask.id == task_id).options(selectinload(ReviewTask.project)))
    if task is None:
        raise HTTPException(status_code=404, detail="review task not found")
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(task, field, value)
    session.commit()
    session.refresh(task)
    return _review_task_read(task)


@router.get(
    "/exports/products.json",
    response_model=ProductsExport,
    summary="Export products JSON",
    description="Return product detail records in a compact export envelope for downstream consumers.",
    operation_id="exportProductsJson",
)
def export_products(
    session: SessionDep,
    project_slug: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ProductsExport:
    statement = select(HKLifeProduct).options(
        selectinload(HKLifeProduct.project),
        selectinload(HKLifeProduct.insurer),
        selectinload(HKLifeProduct.versions),
        selectinload(HKLifeProduct.aliases),
    )
    if project_slug is not None:
        statement = statement.join(Project, HKLifeProduct.project_id == Project.id).where(Project.slug == project_slug)
    products = session.scalars(
        statement.order_by(HKLifeProduct.canonical_name, HKLifeProduct.id).offset(offset).limit(limit)
    ).all()
    product_details = [_product_detail(product) for product in products]
    return ProductsExport(products=product_details, count=len(product_details))
