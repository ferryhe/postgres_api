from dataclasses import dataclass
from os import getenv

from postgres_api import __version__


@dataclass(frozen=True)
class Settings:
    app_name: str = getenv("APP_NAME", "postgres_api")
    app_version: str = getenv("APP_VERSION", __version__)
    database_url: str = getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/postgres_api",
    )


def get_settings() -> Settings:
    return Settings()
