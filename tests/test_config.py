import pytest

from postgres_api.config import get_settings


def test_get_settings_reads_current_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "custom-api")
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    settings = get_settings()

    assert settings.app_name == "custom-api"
    assert settings.app_version == "9.9.9"
    assert settings.database_url == "sqlite+pysqlite:///:memory:"


def test_get_settings_trims_cors_origins(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", " http://localhost:5173,https://example.com ")

    settings = get_settings()

    assert settings.cors_origins == ["http://localhost:5173", "https://example.com"]


def test_get_settings_rejects_wildcard_cors_origin(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "*")

    with pytest.raises(ValueError, match="wildcard"):
        get_settings()


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "file:///tmp/index.html",
        "ftp://example.com",
        "localhost:5173",
        "http://*",
        "https://*.example.com",
        "https://example.com/path",
        "https://example.com?debug=true",
        "https://example.com#fragment",
    ],
)
def test_get_settings_rejects_non_http_or_non_origin_cors_values(monkeypatch, origin: str) -> None:
    monkeypatch.setenv("CORS_ORIGINS", origin)

    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        get_settings()
