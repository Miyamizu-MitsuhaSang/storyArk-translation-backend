from translation_backend.main import app


def test_jobs_routes_are_registered_with_descriptions() -> None:
    paths = app.openapi()["paths"]
    list_operation = paths["/api/v1/jobs"]["get"]
    get_operation = paths["/api/v1/jobs/{job_id}"]["get"]
    cancel_operation = paths["/api/v1/jobs/{job_id}/cancel"]["post"]

    assert list_operation["description"]
    assert list_operation["responses"]["200"]
    assert get_operation["description"]
    assert cancel_operation["description"]
    assert get_operation["responses"]["200"]
    assert cancel_operation["responses"]["200"]
