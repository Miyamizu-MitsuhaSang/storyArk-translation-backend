"""FastAPI dependencies for CAT workbench and workflow use cases."""

from .....application.project.cat.workbench.service import CatWorkbenchService
from .....application.project.cat.workflow.service import CatWorkflowService


_cat_workbench_service = CatWorkbenchService()
_cat_workflow_service = CatWorkflowService(workbench=_cat_workbench_service)


def get_cat_workbench_service() -> CatWorkbenchService:
    return _cat_workbench_service


def get_cat_workflow_service() -> CatWorkflowService:
    return _cat_workflow_service


__all__ = ["get_cat_workbench_service", "get_cat_workflow_service"]
