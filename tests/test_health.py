from fastapi.testclient import TestClient

from postgres_api.config import get_settings
from postgres_api.main import app


def test_health() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": get_settings().app_name,
        "version": get_settings().app_version,
    }
