from fastapi import APIRouter

from .workbench.routes import cat_workbench_router
from .workflow.routes import cat_workflow_router

project_cat_router = APIRouter()
project_cat_router.include_router(cat_workbench_router, tags=["cat_workbench"])
project_cat_router.include_router(cat_workflow_router, tags=["cat_workflow"])
