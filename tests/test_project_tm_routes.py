import importlib.util

from translation_backend.app.api.modules.project.project_content.router import project_content_router
from translation_backend.app.api.modules.project.project_content.tm.routes import (
    list_translation_memories,
    project_tm_router,
    reindex_translation_memories,
    search_translation_memories,
)
from translation_backend.app.api.modules.jobs import routes as jobs_routes


def test_project_tm_module_defines_all_project_tm_operations():
    paths = {route.path for route in project_tm_router.routes}

    assert {
        "/translation-memories",
        "/tm/search",
        "/translation-memories/reindex",
    } <= paths
    assert list_translation_memories.__module__.endswith("project_content.tm.routes")
    assert search_translation_memories.__module__.endswith("project_content.tm.routes")
    assert reindex_translation_memories.__module__.endswith("project_content.tm.routes")
    assert any(
        getattr(route, "original_router", None) is project_tm_router
        for route in project_content_router.routes
    )


def test_project_translation_memory_module_is_removed():
    assert importlib.util.find_spec(
        "translation_backend.app.api.modules.project.project_content.translation_memory"
    ) is None


def test_jobs_use_tm_module_dependency():
    assert jobs_routes.get_translation_memory_service.__module__.endswith(
        "project.project_content.tm.dependencies"
    )
