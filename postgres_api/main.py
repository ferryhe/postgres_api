from fastapi import FastAPI

from postgres_api.config import get_settings

settings = get_settings()

app = FastAPI(
    title="postgres_api",
    version=settings.app_version,
    description="Product catalog ingestion API backed by a Postgres-ready schema.",
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }
