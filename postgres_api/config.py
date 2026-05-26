import os
from dataclasses import dataclass

from postgres_api import __version__


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    database_url: str


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "postgres_api"),
        app_version=os.getenv("APP_VERSION", __version__),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/postgres_api",
        ),
    )
