from postgres_api.config import get_settings


def test_get_settings_reads_current_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "custom-api")
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    settings = get_settings()

    assert settings.app_name == "custom-api"
    assert settings.app_version == "9.9.9"
    assert settings.database_url == "sqlite+pysqlite:///:memory:"
