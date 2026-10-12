# Jobs 能力完善实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 `BackgroundJob` 统一所有异步任务的查询、列表、取消、下载、权限和状态生命周期，并同步真实 API 契约。

**Architecture:** PostgreSQL `background_jobs` 是任务状态唯一事实来源；`app/application/jobs` 负责统一任务用例、权限和脱敏；`app/api/modules/jobs` 只负责 HTTP 参数和错误映射；各业务 application service 继续负责创建任务，`app/tasks` worker 负责领取、执行和提交结果。通过事务行锁和 lease 校验阻止取消任务被 worker 覆盖。

**Tech Stack:** FastAPI、Pydantic v2、Tortoise ORM、Celery、PostgreSQL/SQLite 测试、pytest。

**Spec:** 用户提供的 Jobs 能力补全需求（2026-10-13 会话）。

## Global Constraints

- 不删除已有 Jobs API，不修改前端代码。
- PostgreSQL `background_jobs` 是任务事实来源，Redis 不保存任务最终状态。
- 保持现有任务类型名称和 Tortoise/FastAPI/Celery 架构。
- 所有返回的 `result`、错误和下载信息必须脱敏，不暴露 secret、token、api_key、storage_key、storage_uri 或本地路径。
- 不可见任务统一按 404 处理；取消和下载不能泄露任务存在性。
- 每个任务阶段先写失败测试，再写最小实现；每个阶段运行专项测试后再继续。

### Task 1: 统一任务 Schema 与可见任务查询

**Files:**
- Modify: `app/application/jobs/schemas.py`
- Modify: `app/application/jobs/service.py`
- Modify: `app/api/modules/jobs/routes.py`
- Test: `tests/test_jobs_service.py`, `tests/test_jobs_api_contract.py`, create `tests/test_jobs_list.py`

**Interfaces:**
- `JobStatusResponse` 增加 `resource_type`、`resource_id`、`project_id`、`requested_version`、`attempts`、`max_attempts`、`started_at`、`updated_at`。
- 新增 `JobListQuery`、`JobPage`。
- 新增 `JobsService.list(user, query)`，返回 `JobPage`。
- 保留 `get_status(user, job_id)`，统一返回 `JobStatusResponse`。

- [x] 写列表过滤、游标稳定性和资源 `project_id` 投影测试。
- [x] 运行 `uv run pytest -q tests/test_jobs_list.py tests/test_jobs_service.py`，确认新契约失败。
- [x] 实现状态响应、基于 `(priority, created_at, id)` 的不透明游标和 status/type/project/resource/date/active_only 过滤。
- [x] 在路由注册 `GET /api/v1/jobs`，保留现有单任务路由。
- [x] 运行专项测试并确认通过。

### Task 2: 统一任务错误与下载契约

**Files:**
- Modify: `app/application/jobs/service.py`
- Modify: `app/api/modules/jobs/routes.py`
- Modify: `app/application/jobs/schemas.py`
- Test: `tests/test_jobs_service.py`, create `tests/test_jobs_security.py`

**Interfaces:**
- Jobs service 使用 `JobNotFoundError`、`JobConflictError` 的稳定 code/details。
- 下载错误区分 `JOB_DOWNLOAD_NOT_READY`、`JOB_DOWNLOAD_EXPIRED`、`JOB_DOWNLOAD_INVALID_SIGNATURE`。
- `JobStatusResponse.result` 仅输出允许字段，成功的 `document_export` 结果附带短时 `download_url`。

- [x] 写不可见任务 404、导出下载成功、错误签名/过期/未完成测试。
- [x] 运行测试确认错误码和统一响应尚未满足。
- [x] 实现资源到项目的解析：document、translation_task、terminology_base、translation_memory_library、project；未知资源拒绝。
- [x] 修正 API 错误映射为统一错误结构，安全处理文件名和签名。
- [x] 运行专项测试并确认通过。

### Task 3: 加强 BackgroundJob 状态机与 worker 竞态保护

**Files:**
- Modify: `app/models/jobs.py`
- Modify: `app/tasks/documents.py`, `app/tasks/translation_memory.py`, `app/tasks/terminology.py`, `app/tasks/cat.py`, `app/tasks/translation_tasks.py`
- Test: `tests/test_jobs_worker_state.py`

**Interfaces:**
- `BackgroundJob.claim()` 保持事务行锁、lease 和 retry 语义。
- `complete()`、`fail()` 必须在锁内重新读取任务并校验 `status=running`、worker owner 和未过期 lease。
- 取消后 worker 提交必须失败且不能覆盖 `cancelled`。

- [x] 写取消后 complete、lease 过期重领、超过 max_attempts、错误脱敏测试。
- [x] 运行 worker 状态测试确认失败。
- [x] 收紧 complete/fail/cancel 的状态更新字段和错误码，保证终态不可逆。
- [x] 检查各 worker 在提交结果前使用 `BackgroundJob.complete/fail`，修复绕过状态机的路径。
- [x] 运行专项 worker 测试。

### Task 4: 核对异步任务生产方和幂等行为

**Files:**
- Modify only where gaps are found: `app/application/project/document/service.py`, `app/application/project/terminology/workflows.py`, `app/application/translation_memory/service.py`, `app/application/project/translation_task/service.py`, `app/application/project/cat/workflow/service.py`
- Test: existing producer tests plus `tests/test_jobs_producers.py`

**Interfaces:**
- 所有超过同步阈值的操作返回 `job_id`、`type`、`status` 并使用 HTTP 202。
- 所有可重试生产接口使用 `execute_idempotently`，重复 key 返回同一任务结果，不同 payload 返回 `409 IDEMPOTENCY_CONFLICT`。

- [x] 建立生产方矩阵测试，覆盖 document、terminology、TM、translation task、CAT bulk-action。
- [x] 运行测试确认缺失项。
- [x] 只补齐实际缺口，不重构已经满足契约的业务服务。
- [x] 运行全部 producer 测试。

### Task 5: API 文档、OpenAPI 和完整验证

**Files:**
- Modify: `api-contract/docs/api.md`
- Sync: `docs/api.md`, `src/translation_backend/docs/api.md`, `src/translation_frontend/docs/api.md`, `src/storyark_frontend/docs/api.md`
- Test: `tests/test_jobs_api_contract.py`

- [x] 写 OpenAPI 断言：Jobs 列表、统一响应字段、202/404/409/下载响应。
- [x] 更新第 11 章，写清列表筛选、游标、状态机、权限和下载签名。
- [x] 运行 `scripts/sync-api-docs.sh` 与 `scripts/check-api-docs.sh`。
- [x] 运行 `uv run pytest -q`、`uv run python -m compileall -q app migrations` 和 `git diff --check`。
- [x] 交付报告实现范围、迁移、测试及 PostgreSQL/Redis/Celery/对象存储前置条件。
