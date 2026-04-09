import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from inertia import (
    InertiaVersionConflictException,
    inertia_request_validation_exception_handler,
    inertia_version_conflict_exception_handler,
)
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.config import settings
from backend.app.pages.connect_guide import router as connect_guide_router
from backend.app.pages.dashboard import router as dashboard_router
from backend.app.pages.form_explorer import router as form_explorer_router
from backend.app.pages.form_review import router as form_review_router
from backend.app.pages.settings_page import router as settings_router
from backend.app.pages.test_chat import router as test_chat_router
from backend.app.api.v1.chat_api import router as chat_api_router
from backend.app.api.v1.explorations import router as explorations_api_router
from backend.app.api.v1.forms import router as forms_api_router
from backend.app.api.v1.notifications_api import router as notifications_api_router
from backend.app.api.v1.recordings_api import router as recordings_api_router
from backend.app.api.v1.settings_api import router as settings_api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Agentic.Munster", version="0.1.0")

    # CORS for Vite dev server
    if settings.environment == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.vite_dev_url],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Serve built frontend assets in production
    if settings.environment == "production":
        import os
        from fastapi.staticfiles import StaticFiles

        dist_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
        if os.path.isdir(dist_dir):
            app.mount("/assets", StaticFiles(directory=os.path.join(dist_dir, "assets")), name="static")

    # Inertia exception handlers
    app.add_exception_handler(
        InertiaVersionConflictException,
        inertia_version_conflict_exception_handler,  # type: ignore[arg-type]
    )

    # Routes
    app.include_router(forms_api_router, prefix="/api/v1", tags=["forms"])
    app.include_router(explorations_api_router, prefix="/api/v1", tags=["explorations"])
    app.include_router(settings_api_router, prefix="/api/v1", tags=["settings"])
    app.include_router(chat_api_router, prefix="/api/v1", tags=["chat"])
    app.include_router(notifications_api_router, prefix="/api/v1", tags=["notifications"])
    app.include_router(recordings_api_router, prefix="/api/v1", tags=["recordings"])
    app.include_router(form_explorer_router, tags=["pages"])
    app.include_router(form_review_router, tags=["pages"])
    app.include_router(settings_router, tags=["pages"])
    app.include_router(test_chat_router, tags=["pages"])
    app.include_router(connect_guide_router, tags=["pages"])
    app.include_router(dashboard_router, tags=["pages"])

    return app


app = create_app()
