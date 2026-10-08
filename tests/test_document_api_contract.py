from __future__ import annotations

from translation_backend.app.api.modules.project.document.routes import project_document_router
from translation_backend.app.api.modules.project.routes import project_router
from translation_backend.app.application.project.document.schemas import (
    DocumentResponse,
    DocumentSegmentPage,
    DocumentTaskResponse,
)


def test_document_router_exposes_section_8_operations() -> None:
    operations = {(route.path, method) for route in project_document_router.routes for method in route.methods}

    assert {
        ("", "GET"),
        ("", "POST"),
        ("/{document_id}", "GET"),
        ("/{document_id}", "DELETE"),
        ("/{document_id}/archive", "POST"),
        ("/{document_id}/parse", "POST"),
        ("/{document_id}/segments", "GET"),
        ("/{document_id}/export", "POST"),
    } <= operations
    assert any(getattr(route, "original_router", None) is project_document_router for route in project_router.routes)


def test_document_routes_have_response_contracts_and_descriptions() -> None:
    routes = {(route.path, next(iter(route.methods))): route for route in project_document_router.routes}

    assert routes[("", "GET")].response_model is not None
    assert routes[("/{document_id}", "GET")].response_model is DocumentResponse
    assert routes[("/{document_id}/segments", "GET")].response_model is DocumentSegmentPage
    assert routes[("/{document_id}/parse", "POST")].response_model is DocumentTaskResponse
    assert routes[("/{document_id}/export", "POST")].response_model is DocumentTaskResponse
    assert all(route.description for route in project_document_router.routes)


def test_document_status_response_does_not_expose_storage_path() -> None:
    fields = DocumentResponse.model_fields

    assert "storage_uri" not in fields
    assert {"id", "project_id", "name", "status", "version", "segment_count"} <= set(fields)
