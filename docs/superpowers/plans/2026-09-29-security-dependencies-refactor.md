# Security and API Dependencies Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move framework-independent security helpers into `app/core/security.py` and place FastAPI dependency providers in shared or module-specific dependency modules without changing API behavior.

**Architecture:** Core security exposes password, refresh-token, and JWT primitives only. API shared dependencies expose bearer-token extraction, auth service wiring, and current-user resolution; module dependency files expose only services used by their owning routes.

**Tech Stack:** Python 3.13, FastAPI, PyJWT, pwdlib, Tortoise ORM, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-security-dependencies-design.md`

## Global Constraints

- `app/core/security.py` must not import FastAPI, `fastapi.security`, `Depends`, `Request`, `Header`, `Cookie`, ORM models, or application services.
- Preserve existing service singleton behavior and `AuthError` handling.
- Do not create empty module dependency files.
- Preserve existing API paths and OpenAPI behavior.
- Do not modify unrelated worktree files.

### Task 1: Extract Framework-Independent Security Helpers

**Files:**
- Modify: `app/core/security.py`
- Modify: `app/application/auth/service.py`
- Test: import and helper smoke checks executed from the command line

**Interfaces:**
- Produces `hash_password(password: str) -> str`, `verify_password(password: str, password_hash: str) -> bool`, `hash_refresh_token(value: str) -> str`, `create_access_token(claims: AccessTokenClaims) -> str`, and `decode_access_token(access_token: str) -> dict[str, object]`.
- `AuthService` consumes those helpers while retaining its existing public methods and error behavior.

- [x] **Step 1: Add the security helper implementations and exports.**
- [x] **Step 2: Replace duplicated cryptographic code in `AuthService` with helper calls.**
- [x] **Step 3: Verify `app.core.security` has no FastAPI/application/model imports and import the new helpers.**

### Task 2: Create Shared API Dependencies

**Files:**
- Create: `app/api/shared/dependencies.py`
- Modify: `app/core/security.py`
- Modify: `app/api/modules/auth/routes.py`
- Modify: `app/api/modules/project/routes.py`
- Modify: `app/api/modules/project/api_key/routes.py`
- Modify: `app/api/modules/auth/api_key/routes.py`

**Interfaces:**
- Produces `oauth2_scheme`, `get_auth_service() -> AuthService`, and `get_current_user(token: str | None, service: AuthService) -> User`.

- [x] **Step 1: Move FastAPI bearer-token and current-user provider code into `api/shared/dependencies.py`.**
- [x] **Step 2: Update auth, project, and both API-key route modules to import shared authentication dependencies.**
- [x] **Step 3: Remove all FastAPI dependency exports from `core.security.py` and search for stale imports.**

### Task 3: Create Module-Specific Service Providers

**Files:**
- Create: `app/api/modules/auth/api_key/dependencies.py`
- Create: `app/api/modules/project/dependencies.py`
- Create: `app/api/modules/project/api_key/dependencies.py`
- Create: `app/api/modules/rag/dependencies.py`
- Modify: `app/api/modules/auth/routes.py`
- Modify: `app/api/modules/auth/api_key/routes.py`
- Modify: `app/api/modules/project/routes.py`
- Modify: `app/api/modules/project/api_key/routes.py`
- Modify: `app/api/modules/rag/routes.py`

**Interfaces:**
- Produces `get_api_key_service`, `get_project_service`, `get_project_api_key_service`, and `get_rag_service` in their owning modules.

- [x] **Step 1: Move each existing provider and singleton into its module dependency file.**
- [x] **Step 2: Update routes to consume the new provider paths.**
- [x] **Step 3: Keep the RAG compatibility service module as a re-export surface without duplicating provider state.**

### Task 4: Verify Imports, Contracts, and Runtime Shape

**Files:**
- Test-only command checks; no additional source files required.

- [x] **Step 1: Run the test suite.**
- [x] **Step 2: Run `python -m compileall -q app main.py`.**
- [x] **Step 3: Import the app and inspect OpenAPI paths.**
- [x] **Step 4: Run `git diff --check` and confirm only intended files changed.**
