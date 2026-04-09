from typing import Annotated

from fastapi import Depends
from fastapi.templating import Jinja2Templates
from inertia import Inertia, InertiaConfig, inertia_dependency_factory

from backend.app.config import settings

templates = Jinja2Templates(directory="backend/app/templates")

inertia_config = InertiaConfig(
    templates=templates,
    environment=settings.environment,
    version="1.0",
    dev_url=settings.vite_dev_url,
    root_directory="src",
    entrypoint_filename="main.tsx",
)

inertia_dependency = inertia_dependency_factory(inertia_config)
InertiaDep = Annotated[Inertia, Depends(inertia_dependency)]
