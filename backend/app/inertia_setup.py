from typing import Annotated

from fastapi import Depends
from fastapi.templating import Jinja2Templates
from inertia import Inertia, InertiaConfig, inertia_dependency_factory

from backend.app.config import settings

templates = Jinja2Templates(directory="backend/app/templates")
templates.env.globals["is_dev"] = settings.environment == "development"

_manifest_path = ""
if settings.environment == "production":
    import os
    _candidate = os.path.join(
        os.path.dirname(__file__), "..", "..", "frontend", "dist", "manifest.json"
    )
    if os.path.isfile(_candidate):
        _manifest_path = _candidate

inertia_config = InertiaConfig(
    templates=templates,
    environment=settings.environment,
    version="1.0",
    dev_url=settings.vite_dev_url,
    manifest_json_path=_manifest_path,
    root_directory="src",
    entrypoint_filename="main.tsx",
    assets_prefix="/static" if settings.environment == "production" else "",
)

inertia_dependency = inertia_dependency_factory(inertia_config)
InertiaDep = Annotated[Inertia, Depends(inertia_dependency)]
