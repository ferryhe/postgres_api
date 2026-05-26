from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from postgres_api.models import (
    EvidenceSpan,
    HKInsurer,
    HKLifeProduct,
    HKLifeProductVersion,
    IngestionRun,
    Project,
    SourceDocument,
)

EXTRACTOR_SOURCE = "life_product_extractor"
SUPPORTED_SCHEMA_VERSION = "0.1"


@dataclass(slots=True)
class ImportSummary:
    project_id: int
    insurer_id: int
    ingestion_run_id: int
    products_seen: int = 0
    products_created: int = 0
    products_updated: int = 0
    versions_created: int = 0
    versions_updated: int = 0
    source_documents_created: int = 0
    source_documents_updated: int = 0
    evidence_spans_created: int = 0
    evidence_spans_reused: int = 0
    unsupported_documents: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "insurer_id": self.insurer_id,
            "ingestion_run_id": self.ingestion_run_id,
            "products_seen": self.products_seen,
            "products_created": self.products_created,
            "products_updated": self.products_updated,
            "versions_created": self.versions_created,
            "versions_updated": self.versions_updated,
            "source_documents_created": self.source_documents_created,
            "source_documents_updated": self.source_documents_updated,
            "evidence_spans_created": self.evidence_spans_created,
            "evidence_spans_reused": self.evidence_spans_reused,
            "unsupported_documents": self.unsupported_documents,
            "warnings": self.warnings,
        }


class ExtractorImportError(ValueError):
    """Raised when an extractor bundle cannot be imported."""


def import_extractor_bundle(
    session: Session,
    bundle: Mapping[str, Any],
    *,
    project_slug: str,
    insurer_name: str,
    project_name: str | None = None,
    source_label: str | None = None,
) -> ImportSummary:
    """Import a life_product_extractor candidate/reviewed bundle into existing models.

    The importer is intentionally idempotent for stable business keys:
    project slug, insurer canonical name, product canonical name, product version label,
    source document synthetic URL/sha256, and evidence selector.
    """

    _validate_bundle(bundle)

    now = datetime.now(UTC)
    fixture_set_id = _required_str(bundle, "fixture_set_id")
    products = list(bundle.get("products") or [])
    unsupported_documents = list(bundle.get("unsupported_documents") or [])

    project = _upsert_project(session, slug=project_slug, name=project_name or project_slug)
    insurer = _upsert_insurer(session, canonical_name=insurer_name)
    session.flush()

    run = IngestionRun(
        project=project,
        status="completed",
        source=source_label or EXTRACTOR_SOURCE,
        started_at=now,
        completed_at=now,
        run_metadata={
            "schema_version": bundle.get("schema_version"),
            "fixture_set_id": fixture_set_id,
            "summary": bundle.get("summary"),
            "review_metadata": bundle.get("review_metadata"),
            "unsupported_documents": unsupported_documents,
            "product_count": len(products),
        },
    )
    session.add(run)
    session.flush()

    summary = ImportSummary(
        project_id=project.id,
        insurer_id=insurer.id,
        ingestion_run_id=run.id,
        products_seen=len(products),
        unsupported_documents=len(unsupported_documents),
    )

    source_documents_by_document_id: dict[str, SourceDocument] = {}
    for product_data in products:
        if not isinstance(product_data, Mapping):
            summary.warnings.append("skipped non-object product")
            continue

        product = _upsert_product(session, project=project, insurer=insurer, product_data=product_data, summary=summary)
        session.flush()

        evidence_ids: list[str] = []
        source_ids: set[str] = set()
        seen_product_evidence_ids: set[str] = set()
        for evidence_data in list(product_data.get("evidence") or []):
            if not isinstance(evidence_data, Mapping):
                summary.warnings.append(f"skipped non-object evidence for product {product_data.get('product_id')}")
                continue
            evidence_id = _coerce_str(evidence_data.get("id")) or _evidence_fingerprint(evidence_data)
            if evidence_id in seen_product_evidence_ids:
                product_id = product_data.get("product_id")
                summary.warnings.append(f"skipped duplicate evidence id for product {product_id}: {evidence_id}")
                continue
            seen_product_evidence_ids.add(evidence_id)
            evidence_ids.append(evidence_id)
            if evidence_data.get("source_id") is not None:
                source_ids.add(str(evidence_data["source_id"]))

            document = _upsert_source_document(
                session,
                project=project,
                ingestion_run=run,
                fixture_set_id=fixture_set_id,
                evidence_data=evidence_data,
                cache=source_documents_by_document_id,
                summary=summary,
            )
            _upsert_evidence_span(session, source_document=document, evidence_data=evidence_data, summary=summary)

        _upsert_product_version(
            session,
            product=product,
            product_data=product_data,
            fixture_set_id=fixture_set_id,
            schema_version=str(bundle.get("schema_version")),
            evidence_ids=evidence_ids,
            source_ids=sorted(source_ids),
            summary=summary,
        )

    session.commit()
    return summary


def _validate_bundle(bundle: Mapping[str, Any]) -> None:
    if not isinstance(bundle, Mapping):
        raise ExtractorImportError("bundle must be a JSON object")
    if bundle.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise ExtractorImportError(
            f"unsupported schema_version {bundle.get('schema_version')!r}; expected {SUPPORTED_SCHEMA_VERSION!r}"
        )
    if not bundle.get("fixture_set_id"):
        raise ExtractorImportError("bundle.fixture_set_id is required")
    products = bundle.get("products")
    if products is None or not isinstance(products, list):
        raise ExtractorImportError("bundle.products must be a list")


def _upsert_project(session: Session, *, slug: str, name: str) -> Project:
    project = session.scalar(select(Project).where(Project.slug == slug))
    if project is None:
        project = Project(slug=slug, name=name)
        session.add(project)
    elif name and project.name != name:
        project.name = name
    return project


def _upsert_insurer(session: Session, *, canonical_name: str) -> HKInsurer:
    insurer = session.scalar(select(HKInsurer).where(HKInsurer.canonical_name == canonical_name))
    if insurer is None:
        insurer = HKInsurer(canonical_name=canonical_name)
        session.add(insurer)
    return insurer


def _upsert_product(
    session: Session,
    *,
    project: Project,
    insurer: HKInsurer,
    product_data: Mapping[str, Any],
    summary: ImportSummary,
) -> HKLifeProduct:
    identity = product_data.get("product_identity") or {}
    if not isinstance(identity, Mapping):
        identity = {}
    canonical_name = _coerce_str(identity.get("product_name")) or _required_str(product_data, "product_id")
    product = session.scalar(
        select(HKLifeProduct).where(
            HKLifeProduct.project_id == project.id,
            HKLifeProduct.insurer_id == insurer.id,
            HKLifeProduct.canonical_name == canonical_name,
        )
    )
    product_type = _coerce_str(identity.get("product_class_primary"))
    if product is None:
        product = HKLifeProduct(
            project=project,
            insurer=insurer,
            canonical_name=canonical_name,
            product_type=product_type,
        )
        session.add(product)
        summary.products_created += 1
    else:
        product.product_type = product_type
        summary.products_updated += 1
    return product


def _upsert_product_version(
    session: Session,
    *,
    product: HKLifeProduct,
    product_data: Mapping[str, Any],
    fixture_set_id: str,
    schema_version: str,
    evidence_ids: list[str],
    source_ids: list[str],
    summary: ImportSummary,
) -> HKLifeProductVersion:
    product_id = _required_str(product_data, "product_id")
    version_label = _truncate(f"{fixture_set_id}:{product_id}:v{schema_version}", 120)
    version = session.scalar(
        select(HKLifeProductVersion).where(
            HKLifeProductVersion.product_id == product.id,
            HKLifeProductVersion.version_label == version_label,
        )
    )
    metadata = {
        "import_source": EXTRACTOR_SOURCE,
        "extractor_product_id": product_id,
        "raw_product": _jsonable(product_data),
        "findings_summary": {
            "decrements": len(product_data.get("decrements") or []),
            "benefits": len(product_data.get("benefits") or []),
            "explicit_unknowns": len(product_data.get("explicit_unknowns") or []),
        },
        "source_document_ids": list(product_data.get("source_document_ids") or []),
        "paired_source_scenario_ids": list(product_data.get("paired_source_scenario_ids") or []),
        "evidence_ids": evidence_ids,
        "source_ids": source_ids,
    }
    if version is None:
        version = HKLifeProductVersion(product=product, version_label=version_label)
        session.add(version)
        summary.versions_created += 1
    else:
        summary.versions_updated += 1
    version.summary = json.dumps(metadata["findings_summary"], sort_keys=True)
    version.product_metadata = metadata
    return version


def _upsert_source_document(
    session: Session,
    *,
    project: Project,
    ingestion_run: IngestionRun,
    fixture_set_id: str,
    evidence_data: Mapping[str, Any],
    cache: dict[str, SourceDocument],
    summary: ImportSummary,
) -> SourceDocument:
    document_id = _coerce_str(evidence_data.get("document_id")) or "unknown-document"
    metadata = _source_document_metadata(fixture_set_id=fixture_set_id, document_id=document_id, evidence_data=evidence_data)
    if document_id in cache:
        cached_document = cache[document_id]
        cached_document.document_metadata = _merge_document_metadata(cached_document.document_metadata, metadata)
        return cached_document

    url = _extractor_source_url(fixture_set_id=fixture_set_id, document_id=document_id)
    sha256 = hashlib.sha256(url.encode("utf-8")).hexdigest()
    document = session.scalar(select(SourceDocument).where(SourceDocument.project_id == project.id, SourceDocument.url == url))
    if document is None:
        document = session.scalar(
            select(SourceDocument).where(SourceDocument.project_id == project.id, SourceDocument.sha256 == sha256)
        )

    if document is None:
        document = SourceDocument(
            project=project,
            ingestion_run=ingestion_run,
            url=url,
            sha256=sha256,
            title=document_id,
            content_type="application/vnd.life-product-extractor.evidence+json",
            document_metadata=metadata,
        )
        session.add(document)
        summary.source_documents_created += 1
    else:
        document.ingestion_run = ingestion_run
        document.title = document.title or document_id
        document.document_metadata = _merge_document_metadata(document.document_metadata, metadata)
        summary.source_documents_updated += 1

    cache[document_id] = document
    return document


def _extractor_source_url(*, fixture_set_id: str, document_id: str) -> str:
    return f"extractor://{quote(fixture_set_id, safe='')}/{quote(document_id, safe='')}"


def _source_document_metadata(
    *, fixture_set_id: str, document_id: str, evidence_data: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "import_source": EXTRACTOR_SOURCE,
        "fixture_set_id": fixture_set_id,
        "document_id": document_id,
        "source_ids": sorted({_coerce_str(evidence_data.get("source_id"))} - {None}),
        "evidence": [_evidence_metadata(evidence_data)],
    }


def _upsert_evidence_span(
    session: Session,
    *,
    source_document: SourceDocument,
    evidence_data: Mapping[str, Any],
    summary: ImportSummary,
) -> EvidenceSpan:
    selector = {
        "extractor_evidence_id": _coerce_str(evidence_data.get("id")),
        "source_id": _coerce_str(evidence_data.get("source_id")),
        "document_id": _coerce_str(evidence_data.get("document_id")),
        "section_id": _coerce_str(evidence_data.get("section_id")),
        "line_start": evidence_data.get("line_start"),
        "line_end": evidence_data.get("line_end"),
        "span_start": evidence_data.get("span_start"),
        "span_end": evidence_data.get("span_end"),
        "artifact_id": _coerce_str(evidence_data.get("artifact_id")),
    }
    quote = _coerce_str(evidence_data.get("source_quote")) or ""
    start_offset = _coerce_int(evidence_data.get("span_start"))
    end_offset = _coerce_int(evidence_data.get("span_end"))

    for existing in source_document.evidence_spans:
        if existing.selector == selector and existing.quote == quote:
            summary.evidence_spans_reused += 1
            return existing

    span = EvidenceSpan(
        source_document=source_document,
        start_offset=start_offset,
        end_offset=end_offset,
        quote=quote,
        selector=selector,
    )
    session.add(span)
    summary.evidence_spans_created += 1
    return span


def _merge_document_metadata(existing: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    existing_source_ids = set(merged.get("source_ids") or [])
    new_source_ids = set(new.get("source_ids") or [])
    merged.update({key: value for key, value in new.items() if key not in {"evidence", "source_ids"}})
    merged["source_ids"] = sorted(existing_source_ids | new_source_ids)
    existing_evidence = list(merged.get("evidence") or [])
    seen_keys = {_evidence_metadata_key(item) for item in existing_evidence if isinstance(item, Mapping)}
    for item in new.get("evidence") or []:
        if not isinstance(item, Mapping):
            existing_evidence.append(item)
            continue
        item_key = _evidence_metadata_key(item)
        if item_key not in seen_keys:
            existing_evidence.append(item)
            seen_keys.add(item_key)
    merged["evidence"] = existing_evidence
    return merged


def _evidence_metadata(evidence_data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _coerce_str(evidence_data.get("id")),
        "source_id": _coerce_str(evidence_data.get("source_id")),
        "document_id": _coerce_str(evidence_data.get("document_id")),
        "section_id": _coerce_str(evidence_data.get("section_id")),
        "line_start": evidence_data.get("line_start"),
        "line_end": evidence_data.get("line_end"),
        "span_start": evidence_data.get("span_start"),
        "span_end": evidence_data.get("span_end"),
        "artifact_id": _coerce_str(evidence_data.get("artifact_id")),
        "source_quote": _coerce_str(evidence_data.get("source_quote")),
    }


def _evidence_metadata_key(evidence: Mapping[str, Any]) -> tuple[str, str]:
    evidence_id = _coerce_str(evidence.get("id"))
    if evidence_id is not None:
        return ("id", evidence_id)
    return ("fingerprint", _evidence_fingerprint(evidence))


def _required_str(mapping: Mapping[str, Any], key: str) -> str:
    value = _coerce_str(mapping.get(key))
    if not value:
        raise ExtractorImportError(f"{key} is required")
    return value


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _evidence_fingerprint(evidence_data: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(_jsonable(evidence_data), sort_keys=True).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{value[: max_length - 13]}:{digest}"
