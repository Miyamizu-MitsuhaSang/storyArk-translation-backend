# Security and API Dependency Boundary

## Goal

Separate framework-independent security primitives from FastAPI dependency providers while keeping authentication and service wiring behavior unchanged.

## Architecture

`app/core/security.py` contains password hashing, refresh-token hashing, JWT creation, and JWT decoding helpers. It must not import FastAPI, ORM models, application services, or request-layer types.

`app/api/shared/dependencies.py` contains cross-module HTTP dependencies: `oauth2_scheme`, `get_auth_service`, and `get_current_user`. Business-module service providers live beside their routes: auth API-key, project, project API-key, and RAG providers each stay in their owning module.

`AuthService` remains responsible for authentication use cases and persistence orchestration. It delegates cryptographic operations to `core.security`; route handlers continue to depend on application services through provider functions.

## Dependency Placement

| Dependency | Location | Reason |
| --- | --- | --- |
| `oauth2_scheme` | `app/api/shared/dependencies.py` | FastAPI bearer-token extraction reused by multiple modules |
| `get_current_user` | `app/api/shared/dependencies.py` | Cross-module authenticated-user dependency |
| `get_auth_service` | `app/api/shared/dependencies.py` | Required by the shared user dependency and auth routes |
| `get_api_key_service` | `app/api/modules/auth/api_key/dependencies.py` | User API-key module only |
| `get_project_service` | `app/api/modules/project/dependencies.py` | Project routes only |
| `get_project_api_key_service` | `app/api/modules/project/api_key/dependencies.py` | Project API-key routes only |
| `get_rag_service` | `app/api/modules/rag/dependencies.py` | RAG routes only |

No empty module dependency files are introduced. Existing route imports are updated to these canonical locations.

## Compatibility and Error Behavior

`get_current_user` continues to raise `AuthError` for missing or invalid access tokens, allowing the existing application-level exception handler to produce the same response. The dependency providers return the existing singleton service instances, so no lifecycle or state behavior changes.

## Verification

Verify that `core.security` imports without FastAPI, all routes import successfully, the OpenAPI schema contains the same paths, the full test suite passes, `compileall` succeeds, and no stale imports from `core.security` remain.
