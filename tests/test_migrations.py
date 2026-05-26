from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_alembic_upgrade_sqlite(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "migration.sqlite3"
    database_url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)

    assert {
        "projects",
        "ingestion_runs",
        "source_documents",
        "artifacts",
        "evidence_spans",
        "review_tasks",
        "hk_insurers",
        "hk_life_products",
        "hk_life_product_versions",
        "hk_life_product_aliases",
    }.issubset(set(inspector.get_table_names()))
