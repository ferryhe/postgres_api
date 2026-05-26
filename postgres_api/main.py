from typing import get_args

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from postgres_api.api import router as catalog_router
from postgres_api.config import Settings, get_settings
from postgres_api.schemas import ClientConfig, ReviewTaskStatus

TAGS_METADATA = [
    {"name": "system", "description": "Service health and frontend bootstrap endpoints."},
    {"name": "catalog", "description": "Read-only project, product, source document, review task, and export APIs."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="postgres_api catalog service",
        version=settings.app_version,
        description=(
            "Postgres-backed product catalog and review API for downstream ai_interface clients. "
            "OpenAPI metadata is intended to support typed client generation."
        ),
        openapi_tags=TAGS_METADATA,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(catalog_router)

    @app.get(
        "/health",
        tags=["system"],
        summary="Check service health",
        description="Return basic service status and version metadata.",
        operation_id="getHealth",
    )
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": settings.app_version,
        }

    @app.get(
        "/client-config",
        response_model=ClientConfig,
        tags=["system"],
        summary="Fetch ai_interface bootstrap configuration",
        description="Return stable paths, features, and enum values needed by the ai_interface frontend.",
        operation_id="getClientConfig",
    )
    def client_config() -> ClientConfig:
        return ClientConfig(
            service=settings.app_name,
            version=settings.app_version,
            openapi_url=app.openapi_url,
            docs_url=app.docs_url or "",
            features=[
                "projects",
                "products",
                "source_documents",
                "review_tasks",
                "products_export",
            ],
            review_statuses=list(get_args(ReviewTaskStatus)),
            base_path="/",
            paths={
                "projects": "/projects",
                "products": "/products",
                "product_detail": "/products/{product_id}",
                "source_documents": "/source-documents",
                "review_tasks": "/review-tasks",
                "review_task_detail": "/review-tasks/{task_id}",
                "products_export": "/exports/products.json",
                "openapi": app.openapi_url,
                "docs": app.docs_url or "",
            },
        )

    return app


app = create_app()
