from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from postgres_api.db import Base
from postgres_api.models import (
    HKInsurer,
    HKLifeProduct,
    HKLifeProductAlias,
    HKLifeProductVersion,
    Project,
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
