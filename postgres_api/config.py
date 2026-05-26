import os
from dataclasses import dataclass

from postgres_api import __version__


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    database_url: str
    cors_origins: list[str]


def _parse_csv_env(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "postgres_api"),
        app_version=os.getenv("APP_VERSION", __version__),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/postgres_api",
        ),
        cors_origins=_parse_csv_env(os.getenv("CORS_ORIGINS")),
    )
