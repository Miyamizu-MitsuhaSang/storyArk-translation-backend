from translation_backend.main import app


def test_project_invitation_routes_are_registered_under_expected_prefixes() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/projects/{project_id}/member-candidates": {"get"},
        "/api/v1/projects/{project_id}/invitations": {"get", "post"},
        "/api/v1/projects/{project_id}/invitations/{invitation_id}": {"delete"},
        "/api/v1/projects/{project_id}/invite-codes": {"get", "post"},
        "/api/v1/projects/{project_id}/invite-codes/{invite_code_id}": {"delete"},
        "/api/v1/auth/me/project-invitations": {"get"},
        "/api/v1/auth/me/project-invitations/{invitation_id}/accept": {"post"},
        "/api/v1/auth/me/project-invitations/{invitation_id}/decline": {"post"},
        "/api/v1/auth/me/project-invite-codes/redeem": {"post"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert methods <= set(paths[path])
        for method in methods:
            assert paths[path][method].get("description")


def test_invite_code_schema_never_exposes_hash() -> None:
    schema = app.openapi()["components"]["schemas"]["InviteCodeResponse"]
    assert "code_hash" not in schema["properties"]
