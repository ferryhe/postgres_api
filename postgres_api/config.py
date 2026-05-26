import os
from dataclasses import dataclass
from urllib.parse import urlparse

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


def _parse_cors_origins_env(value: str | None) -> list[str]:
    origins = _parse_csv_env(value)
    for origin in origins:
        parsed = urlparse(origin)
        if origin == "*":
            raise ValueError("CORS_ORIGINS must list explicit http(s) origins; wildcard '*' is not allowed")
        if origin.lower() == "null":
            raise ValueError("CORS_ORIGINS must list explicit http(s) origins; 'null' is not allowed")
        if parsed.scheme == "file":
            raise ValueError("CORS_ORIGINS must list explicit http(s) origins; file:// origins are not allowed")
        try:
            hostname = parsed.hostname
            _port = parsed.port
        except ValueError as exc:
            raise ValueError(f"CORS_ORIGINS entries must be valid origins: {origin!r}") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not hostname:
            raise ValueError(f"CORS_ORIGINS entries must be explicit http(s) origins: {origin!r}")
        if "*" in hostname:
            raise ValueError(f"CORS_ORIGINS entries must not include wildcard hosts: {origin!r}")
        if parsed.path or parsed.params or parsed.query or parsed.fragment:
            raise ValueError(f"CORS_ORIGINS entries must not include path, query, or fragment: {origin!r}")
        if parsed.username or parsed.password:
            raise ValueError(f"CORS_ORIGINS entries must not include credentials: {origin!r}")
    return origins


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "postgres_api"),
        app_version=os.getenv("APP_VERSION", __version__),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/postgres_api",
        ),
        cors_origins=_parse_cors_origins_env(os.getenv("CORS_ORIGINS")),
    )
