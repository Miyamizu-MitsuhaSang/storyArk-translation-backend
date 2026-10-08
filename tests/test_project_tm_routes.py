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


def test_api_service_compatibility_modules_are_removed():
    for module in (
        "translation_backend.app.api.modules.auth.service",
        "translation_backend.app.api.modules.auth.api_key.service",
        "translation_backend.app.api.modules.project.service",
        "translation_backend.app.api.modules.project.api_key.service",
        "translation_backend.app.api.modules.project.project_content.context.service",
        "translation_backend.app.api.modules.project.project_content.terminology.service",
        "translation_backend.app.api.modules.project.project_content.worldview.service",
        "translation_backend.app.api.modules.rag.service",
        "translation_backend.app.api.modules.rag.sdk_adapter",
        "translation_backend.app.application.translation_memory.dependencies",
    ):
        assert importlib.util.find_spec(module) is None


def test_jobs_module_does_not_export_translation_memory_dependencies():
    assert not hasattr(jobs_routes, "get_translation_memory_service")
