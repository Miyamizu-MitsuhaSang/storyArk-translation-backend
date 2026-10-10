# Translation Workspace API 第 15 章实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `docs/api.md` 第 15 章的翻译设置、术语工作流、版本/文件、项目 API key、翻译任务和用量分析契约实现为可测试的 FastAPI 后端能力。

**Architecture:** 保留现有 `app/api -> app/application -> app/domain -> app/repositories -> app/models` 分层。复用现有 Worldview、Terminology、Document、ProjectApiKeyBinding、BackgroundJob 和 AIUsageRecord；新增的配置子资源、项目版本、翻译任务和分析聚合分别建立独立模型/服务，路由只负责 HTTP 入参、鉴权和响应。小型操作同步完成，大型导入/导出/术语提取/挖掘/翻译通过统一 `BackgroundJob` 生命周期执行。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、Tortoise ORM、Aerich、PostgreSQL、Celery/Redis、pytest、现有本地对象存储和 API key AES-256-GCM 加密链路。

**Spec:** `docs/api.md:935-1250`（契约源为 `../../api-contract/docs/api.md`，修改契约后运行同步脚本）。

## Global Constraints

- 所有新增路由相对于 `/api/v1`；除公开模板目录外要求 Bearer access token 和项目成员校验。
- 资源不可见统一按 `404` 返回，不能通过项目、版本、术语库、key 或任务 ID 探测其他资源。
- 列表统一 `page_size`（1..100，默认 20）、不透明 `cursor` 和 `{items,next_cursor,total}`。
- 写请求读取 `X-Request-ID`；可重试的创建、批量、导入、导出和任务写请求必须使用 `Idempotency-Key`。
- 配置、术语、绑定等可编辑资源使用 `revision` 或 `If-Match`；冲突返回 `409 VERSION_CONFLICT` 并携带当前 revision。
- API key 项目路由只处理绑定关系；任何响应、日志、审计、任务结果和导出都不得出现明文 secret。
- `AIUsageRecord` 是用量事实来源；先写 PostgreSQL，再可选写 Redis 缓存，Redis 不可用时回退 PostgreSQL。
- 本计划不把本地 SQLite、OpenAPI 注册或文档同步当作 PostgreSQL/Redis/Celery/provider 运行时可用性证明。

## Baseline And File Map

当前已存在并可复用：

- `app/models/project.py` 中的 `Worldview`、`TerminologyBase`、`TerminologyTerm`、`ProjectApiKeyBinding`；
- `app/models/document.py`、`app/application/project/document/` 中的文档和片段导入/导出；
- `app/models/jobs.py`、`app/application/jobs/`、`app/tasks/documents.py` 的后台任务生命周期；
- `app/models/ai_usage.py`、`app/repositories/usage.py` 的用量明细基础模型；
- `app/application/idempotency.py`、`app/application/project/audit.py` 的幂等和审计基础设施。

第 15 章目前缺失的运行时路径包括翻译设置子资源、术语导入/导出/批量/清空/提取/挖掘、项目版本、翻译任务和两个 analytics 路由。现有项目 API key 路由还需要补上任务引用检查和与新任务模型的契约联动。

---

### Task 1: 固化第 15 章共享 HTTP 契约

**Files:**
- Modify: `app/core/schemas.py`（新增统一分页、错误和 revision 冲突响应模型）
- Modify: `app/api/shared/dependencies.py`（项目成员读取、manager、owner、报表读取依赖）
- Modify: `app/application/idempotency.py`（把 `IdempotencyConflictError` 映射为统一 `409`）
- Modify: `app/api/router.py`、`app/api/modules/auth/routes.py`、`app/api/modules/project/routes.py`（注册共享异常处理）
- Create: `app/application/project/shared.py`（项目可见性、角色、游标和 `If-Match` 解析的应用层辅助函数）
- Test: `tests/test_translation_workspace_contract.py`

**Interfaces:**
- `require_project_member(user, project_id) -> ProjectMember`
- `require_project_role(user, project_id, roles: frozenset[str]) -> ProjectMember`
- `decode_cursor(cursor: str | None) -> int` / `encode_cursor(offset: int) -> str`
- `expected_revision(request: Request, body_revision: int | None) -> int | None`

- [x] **Step 1: 写失败测试。** 覆盖 viewer 访问配置读取成功、非成员得到 `404`、translator 访问管理写入得到 `403`、非法游标得到统一 `422`、重复幂等键请求体不一致得到 `409`。
- [x] **Step 2: 运行失败测试。** 运行 `uv run pytest tests/test_translation_workspace_contract.py -q`，确认共享依赖和异常响应尚未满足断言。
- [x] **Step 3: 实现共享辅助。** 复用现有 `ProjectRepository.find_membership` 和 `ProjectPolicy`，不要在路由中直接查询 `ProjectMember`；将资源不可见错误统一转换为已有 `{error:{code,message,details,request_id}}` 形状。
- [x] **Step 4: 实现并验证幂等。** 对创建、批量、导入、导出和任务接口调用 `execute_idempotently`；相同 key 且 payload 相同重放第一次响应，相同 key 且 payload 不同返回 `409`。
- [x] **Step 5: 运行测试。** 运行 `uv run pytest tests/test_translation_workspace_contract.py tests/test_idempotency_redis.py -q`。
- [ ] **Step 6: 提交。** `git add app/core/schemas.py app/api app/application/idempotency.py tests/test_translation_workspace_contract.py && git commit -m "feat: add translation workspace API contract foundations"`。

### Task 2: 实现 Translation settings

**Files:**
- Modify: `app/models/project.py`（复用 `Worldview.style_guide/default_tone/version` 作为 worldview/tone/revision 来源）
- Create: `app/models/translation_settings.py`（`TranslationRole`、`TranslationRule`、`CultureRule`）
- Modify: `app/models/__init__.py`（注册新增模型）
- Create: `app/application/project/translation_settings/__init__.py`、`app/api/modules/project/translation_settings/__init__.py`
- Create: `app/application/project/translation_settings/schemas.py`
- Create: `app/application/project/translation_settings/repository.py`
- Create: `app/application/project/translation_settings/service.py`
- Create: `app/api/modules/project/translation_settings/routes.py`
- Create: `app/api/modules/project/translation_settings/dependencies.py`
- Modify: `app/api/modules/project/routes.py`（挂载 `/translation-settings`）
- Create: `migrations/models/12_20261008_add_translation_settings.py`
- Test: `tests/test_translation_settings_service.py`、`tests/test_translation_settings_api.py`

**Interfaces:**
- `TranslationSettingsService.get(user, project_id) -> TranslationSettingsResponse`
- `TranslationSettingsService.update(user, project_id, request, expected_revision) -> TranslationSettingsResponse`
- `TranslationSettingsService.list_roles/list_rules/list_culture_rules(...) -> Page[...]`
- `TranslationSettingsService.initialize(user, project_id, template_id, expected_revision, confirm_replace, idempotency_key) -> TranslationSettingsResponse`

**Routes covered:** `/projects/{project_id}/translation-settings`、`/roles`、`/roles/{role_id}`、`/rules`、`/rules/{rule_id}`、`/culture-rules`、`/culture-rules/{rule_id}`、`GET /translation-templates`、`POST /projects/{project_id}/translation-settings/initialize`。

- [x] **Step 1: 写失败测试。** 覆盖 `GET/PATCH /projects/{project_id}/translation-settings`、revision 冲突、模板公开目录、角色/规则/文化规则 CRUD、category 规则缺少 category、重复规则幂等和初始化确认条件。
- [x] **Step 2: 运行失败测试。** 运行 `uv run pytest tests/test_translation_settings_service.py tests/test_translation_settings_api.py -q`，确认路由和模型不存在或响应不匹配。
- [x] **Step 3: 增加模型与迁移。** 三个子资源都保存 `project_id`、稳定 UUID、业务字段、`revision`、`created_at`、`updated_at`、软删除标记；建立项目范围的唯一约束，避免重试产生重复规则，并在 `app/models/__init__.py` 注册模型。迁移不得删除已有 Worldview 数据。
- [x] **Step 4: 实现服务。** 将 `Worldview.style_guide` 映射为 `worldview`、`default_tone` 映射为 `tone`；更新时对 Worldview `version` 加一并检查 `revision`。`owner/manager` 才能写入，translator 及以上可读。
- [x] **Step 5: 实现模板初始化。** 在 `templates.py` 中维护只读 `rpg` 模板目录；`confirm_replace != true` 返回 `422 CONFIRMATION_REQUIRED`，revision 不符返回 `409 VERSION_CONFLICT`，初始化写审计事件但不删除成员或模板目录。
- [x] **Step 6: 运行测试。** 运行 `uv run pytest tests/test_translation_settings_service.py tests/test_translation_settings_api.py -q`，并检查 OpenAPI 中所有 15.1 路径和响应模型。
- [ ] **Step 7: 提交。** `git add app/models app/application/project/translation_settings app/api/modules/project/translation_settings app/api/modules/project/routes.py migrations/models/12_20261008_add_translation_settings.py tests/test_translation_settings_* && git commit -m "feat: implement translation settings APIs"`。

### Task 3: 实现术语导入、导出、批量和异步挖掘

**Files:**
- Modify: `app/application/project/terminology/schemas.py`、`app/application/project/terminology/service.py`、`app/repositories/terminology.py`
- Create: `app/application/project/terminology/workflows.py`
- Modify: `app/api/modules/project/project_content/terminology/routes.py`（新增 workflow 路由）
- Create: `app/tasks/terminology.py`
- Modify: `app/application/jobs/service.py`（让 terminology job 按项目可见性返回）
- Modify: `app/models/jobs.py`（补充 `terminology_import/export/extract/mine` 类型常量或校验）
- Test: `tests/test_terminology_workflows.py`、`tests/test_terminology_jobs.py`

**Interfaces:**
- `TerminologyWorkflowService.import_terms(..., format, content/file, on_conflict, idempotency_key) -> ImportResult | JobAccepted`
- `TerminologyWorkflowService.export_terms(...) -> FileResponseData | JobAccepted`
- `TerminologyWorkflowService.bulk_action(...) -> BulkActionResponse`
- `TerminologyWorkflowService.clear(...) -> ClearResult | JobAccepted`
- `TerminologyWorkflowService.extract(...) -> JobStatusResponse`
- `TerminologyWorkflowService.mine(...) -> JobStatusResponse`

**Routes covered:** `/projects/{project_id}/terminology-bases/{base_id}/terms/import`, `/terms/export`, `/terms/bulk-action`, `/terms/clear`, `/projects/{project_id}/terminology/extract`, `/projects/{project_id}/terminology/mine`。

- [x] **Step 1: 写失败测试。** 覆盖 CSV/JSON 行号保留、`update|skip|error` 冲突策略、无效行不静默丢弃、文件流安全文件名、`term_ids` 1..100、delete 二次确认、expected revisions、expected count、跨项目文件/TM 拒绝和 job 类型。
- [x] **Step 2: 运行失败测试。** 运行 `uv run pytest tests/test_terminology_workflows.py tests/test_terminology_jobs.py -q`。
- [x] **Step 3: 实现同步路径。** 复用 TerminologyRepository 和已有 revision/audit 逻辑；导入在单个事务中写入，返回 `created/updated/skipped/invalid_rows`；导出只读取当前项目术语，使用 CSV/JSON 序列化并设置安全 `Content-Disposition`。
- [x] **Step 4: 实现破坏性操作。** bulk delete/clear 使用事务或可恢复 job；clear 必须 `confirm=true`、`Idempotency-Key`、`expected_count` 精确匹配，超过同步阈值返回 `202`，不得只删除部分记录后报告成功。
- [x] **Step 5: 实现后台 job。** `app/tasks/terminology.py` 通过 `BackgroundJob.claim/complete/fail` 执行异步导入导出、文件术语提取和 TM 挖掘；结果保存候选术语的来源文件、segment、频次和 confidence，不自动覆盖 approved 词条。
- [x] **Step 6: 运行测试。** 运行 `uv run pytest tests/test_terminology_workflows.py tests/test_terminology_jobs.py tests/test_jobs_service.py -q`，确认 job 结果不含 secret 或原始 provider payload。
- [ ] **Step 7: 提交。** `git add app/application/project/terminology app/api/modules/project/project_content/terminology app/tasks/terminology.py app/application/jobs app/models/jobs.py tests/test_terminology_* && git commit -m "feat: add terminology workflow APIs"`。

### Task 4: 增加项目版本和版本文件查询

**Files:**
- Create: `app/models/version.py`（`ProjectVersion`）
- Modify: `app/models/project.py`（增加项目级 `next_version_number` 持久化计数器）
- Modify: `app/models/document.py`（增加 nullable `version_id`；保留现有文档解析 `version` 整数，不复用其语义）
- Modify: `app/models/__init__.py`（注册 `ProjectVersion`）
- Create: `app/application/project/version/__init__.py`、`app/api/modules/project/version/__init__.py`
- Create: `app/application/project/version/schemas.py`
- Create: `app/application/project/version/service.py`
- Create: `app/api/modules/project/version/routes.py`
- Modify: `app/api/modules/project/routes.py`
- Modify: `app/application/project/document/schemas.py`、`app/application/project/document/service.py`、`app/api/modules/project/document/routes.py`（允许上传时显式关联版本并校验项目归属）
- Create: `migrations/models/13_20261008_add_project_versions.py`
- Test: `tests/test_project_versions_api.py`

**Interfaces:**
- `VersionService.list(user, project_id, q, sort, page_size, cursor) -> VersionPage`
- `VersionService.create(user, project_id, request) -> VersionResponse`
- `VersionService.list_files(user, project_id, version_id, page_size, cursor) -> FilePage`

**Routes covered:** `GET/POST /projects/{project_id}/versions`、`GET /projects/{project_id}/versions/{version_id}/files`。

- [x] **Step 1: 写失败测试。** 覆盖系统自动分配整数 `version_number`、项目间独立编号、并发创建不冲突、删除后不复用编号、名称可空且可重复、名称搜索/排序/游标、版本跨项目 `404`、空版本、同名文件、文件只返回当前项目且字段为 `id/name/source_language/format/updated_at/size_bytes`，以及文档上传的版本归属校验。
- [x] **Step 2: 运行失败测试。** 运行 `uv run pytest tests/test_project_versions_api.py -q`，确认版本模块尚不存在时测试按预期失败。
- [x] **Step 3: 实现模型和迁移。** `ProjectVersion.version_number` 使用整数并通过项目级 `next_version_number` 计数器分配；在同一事务内锁定项目行、创建版本并递增计数器，联合唯一约束防止重复。 `name` 可空且不唯一；`Document.version_id` 为空兼容已有数据，文档上传允许显式关联同项目版本。
- [x] **Step 4: 实现服务和路由。** owner/manager 可创建，所有成员可读取；默认按 `version_number` 倒序，名称仅用于搜索和显式名称排序。查询版本前验证项目成员和版本归属；文档和版本必须属于同一项目，资源不可见统一返回 `404`。
- [x] **Step 5: 运行测试。** 运行 `uv run pytest tests/test_project_versions_api.py tests/test_document_api_contract.py tests/test_document_service.py tests/test_document_models.py -q`，并检查 OpenAPI 中 Task 4 的两个版本路径和 `version_number` 响应字段。
- [ ] **Step 6: 提交。** `git add app/models/version.py app/models/project.py app/models/document.py app/models/__init__.py app/application/project/version app/application/project/document app/api/modules/project/version app/api/modules/project/document app/api/modules/project/routes.py migrations/models/13_20261008_add_project_versions.py tests/test_project_versions_api.py && git commit -m "feat: add project versions and version files"`。

### Task 5: 补强项目 API key 绑定安全边界

**实现内容：** 收紧项目与用户级 API key 的绑定边界。项目接口只管理 `api_key_id` 及其绑定元数据，不接触或返回明文 secret；绑定前校验 key 属于当前用户且处于可用状态，默认绑定在事务中保持唯一。删除项目绑定只解除关系，不删除用户级 credential；当绑定仍被排队或执行中的翻译任务引用时，必须拒绝删除或停用并返回 `409 API_KEY_IN_USE`。所有响应、日志、审计和任务结果都要保持脱敏。

用户级 API key 创建请求默认要求 HTTPS；仅在部署明确配置可信 TLS 反向代理时才接受 `X-Forwarded-Proto: https`。HTTPS 检查在请求体解析前执行，服务端随后使用 AES-256-GCM 加密落库，故该方案是 TLS 加应用层静态加密，不是严格端到端加密。

**Files:**
- Modify: `app/application/project/api_key/service.py`、`app/application/project/api_key/schemas.py`、`app/api/modules/project/api_key/routes.py`
- Modify: `app/repositories/api_key.py`
- Test: `tests/test_project_api_key_security.py`

- [x] **Step 1: 写失败测试。** 覆盖非本人 key 返回 `404`、inactive key 不可绑定、重复绑定幂等、同项目只有一个默认绑定、删除绑定不删除用户级 credential、HTTPS 请求体解析前拦截，以及所有 key 响应/日志/审计不含明文 secret。
- [x] **Step 2: 运行失败测试。** 运行 `uv run pytest tests/test_project_api_key_security.py -q`，先验证缺失 HTTPS helper 的预期失败，再进入实现后的绿灯验证。
- [x] **Step 3: 收紧绑定服务。** 保持用户级 API key 的 AES-256-GCM 加密和外部密钥版本；项目 API key 路由只接受 `api_key_id`，只返回脱敏元数据，并用事务保证默认绑定唯一；删除用户级 key 前检查项目绑定，停用 key 后禁止重新激活项目绑定。
- [x] **Step 4: 运行测试。** 运行 `uv run pytest tests/test_project_api_key_security.py ../../tests/test_auth_api_key_api.py -q`、`uv run pytest -q`、`uv run python -m compileall -q app main.py` 和 `git diff --check`；未创建提交，以保留 Task 2–4 的同一工作区改动。

### Task 6: 实现 Translation tasks 创建、查询和 worker 边界

**实现内容：** 建立翻译任务的创建、列表、详情查询和后台执行边界。创建时校验目标语言、源语言、项目文件、项目版本和当前用户 API key 的归属及状态，并通过幂等键避免重复创建。任务模型记录可追踪的状态、进度、文件关联和用户级凭据快照；同一用户的 API key 可跨项目复用，不建立项目级 API key 依赖。worker 只执行定义好的状态迁移，provider 未配置时明确失败，不伪造成功结果。该任务还负责保护被活动任务引用的用户级 API key，避免运行中凭据被删除或停用。

**Files:**
- Create: `app/models/translation_task.py`（`TranslationTask`、`TranslationTaskFile`）
- Modify: `app/models/__init__.py`（注册任务模型）
- Create: `app/application/project/translation_task/__init__.py`、`app/api/modules/project/translation_task/__init__.py`
- Create: `app/application/project/translation_task/schemas.py`
- Create: `app/application/project/translation_task/repository.py`
- Create: `app/application/project/translation_task/service.py`
- Create: `app/api/modules/project/translation_task/routes.py`
- Create: `app/tasks/translation_tasks.py`
- Modify: `app/api/modules/project/routes.py`、`app/application/jobs/service.py`
- Create: `migrations/models/14_20261008_add_translation_tasks.py`
- Test: `tests/test_translation_tasks_service.py`、`tests/test_translation_tasks_api.py`

**Interfaces:**
- `TranslationTaskService.create(user, project_id, request, idempotency_key) -> TranslationTaskResponse`
- `TranslationTaskService.list(user, project_id, query) -> TranslationTaskPage`
- `TranslationTaskService.get(user, project_id, task_id) -> TranslationTaskResponse`
- `TranslationTaskWorker.run(task_id) -> dict[str, object]`

**Routes covered:** `GET/POST /projects/{project_id}/translation-tasks`、`GET /projects/{project_id}/translation-tasks/{task_id}`。

- [x] **Step 1: 写失败测试。** 覆盖目标语言非空且不重复、目标语言不能等于源语言、文件属于项目且源语言匹配、用户级 API key 属于当前用户且 active、owner/manager/translator 可创建、viewer/reviewer 不能创建、默认状态 `queued` 和 progress `0`；活动任务引用的用户级 key 删除/停用返回 `409 API_KEY_IN_USE`。
- [x] **Step 2: 运行失败测试。** 运行 `uv run pytest tests/test_translation_tasks_service.py tests/test_translation_tasks_api.py -q`。
- [x] **Step 3: 实现模型和迁移。** 任务保存名称、语言、状态 `queued|translating|review|completed|failed|cancelled`、整数 progress 0..100、version_id、用户级 `api_key_id` 快照和创建人；文件用 join 表关联，不把文件 ID 作为不可校验 JSON。
- [x] **Step 4: 实现创建服务和 key 引用保护。** 在事务中验证项目文件、版本和用户级 API key；用 `execute_idempotently` 防止重复创建；响应只返回 provider/label/masked_secret 和用户 key UUID，不返回 credential secret。同步修改 `ApiKeyService.delete/update`，检查 queued/translating 任务引用并返回 `409 API_KEY_IN_USE`。
- [x] **Step 5: 实现状态查询和 worker。** 客户端没有 PATCH 任务状态接口；worker 只能按允许的状态转换更新进度。provider 适配器使用明确接口，未配置 provider 时以 `PROVIDER_NOT_CONFIGURED` 失败，不伪造完成结果。
- [x] **Step 6: 运行测试。** 运行 `uv run pytest tests/test_translation_tasks_service.py tests/test_translation_tasks_worker.py tests/test_translation_tasks_api.py tests/test_project_api_key_security.py -q`，再检查 OpenAPI 的 GET/POST 列表和 GET 详情路径。
- [ ] **Step 7: 提交。** `git add app/models/translation_task.py app/application/project/translation_task app/api/modules/project/translation_task app/tasks/translation_tasks.py app/application/project/api_key app/api/modules/project/api_key app/application/jobs/service.py app/api/modules/project/routes.py migrations/models/14_20261008_add_translation_tasks.py tests/test_translation_tasks_* tests/test_project_api_key_security.py && git commit -m "feat: add translation task APIs"`。

### Task 7: 完成 AI usage analytics 和可选 Redis 缓存

**实现内容：** 将 AI 用量记录和统计查询实现为独立能力。写入侧保存不可变、非负的 token/cost 事实，并按 provider 与 request ID 去重；查询侧提供用户级和项目级聚合，支持时间范围、时区、粒度和 API key/model 过滤，完整补齐无数据时间桶。PostgreSQL 是唯一事实来源，Redis 只作为短 TTL 的可选缓存，缓存不可用时自动回退数据库；项目分析还必须校验报表权限和 key 归属，不能通过统计接口泄露其他项目数据。

**Files:**
- Modify: `app/models/ai_usage.py`、`app/repositories/usage.py`（非负约束、不可变写入、过滤和聚合接口）
- Create: `app/application/analytics/schemas.py`
- Create: `app/application/analytics/service.py`
- Create: `app/application/analytics/__init__.py`、`app/api/modules/analytics/__init__.py`
- Create: `app/infrastructure/analytics/cache.py`
- Create: `app/api/modules/analytics/routes.py`
- Modify: `app/api/router.py`、`app/api/modules/project/routes.py`、`app/models/__init__.py`
- Create: `migrations/models/15_20261008_harden_ai_usage_analytics.py`
- Test: `tests/test_usage_analytics_service.py`、`tests/test_usage_analytics_api.py`

**Interfaces:**
- `UsageAnalyticsService.record(event: UsageEvent) -> AIUsageRecord`
- `UsageAnalyticsService.for_user(user, query) -> UsageAnalyticsResponse`
- `UsageAnalyticsService.for_project(user, project_id, query) -> UsageAnalyticsResponse`
- `build_usage_cache_key(scope_id, query) -> str`

- [x] **Step 1: 写失败测试。** 覆盖成功/失败/超时和失败部分用量、provider+request_id 去重、用户和项目隔离、`day` 31 天上限、`hour` 7 天上限、from/to 互斥、时区分桶、空桶补零、cost 字符串返回和 project key 归属校验。
- [x] **Step 2: 运行失败测试。** 已确认缺少 analytics 模块时测试红灯。
- [x] **Step 3: 实现事实写入。** `record` 只接受非负 token/cost；重复 `(provider, provider_request_id)` 返回原记录；明细模型拒绝更新，不保存 prompt/completion/secret。
- [x] **Step 4: 实现聚合。** 按 `completed_at` 范围过滤，兼容 SQLite 的确定性 Python 聚合；按指定时区生成完整升序时间桶，并按 API key/model 汇总。
- [x] **Step 5: 接入 Redis 可选缓存。** 缓存 key 包含 scope、完整过滤条件、时间范围、时区和粒度；TTL 限制为 30..120 秒；Redis 异常时回退数据库。
- [x] **Step 6: 实现两条路由。** 已实现用户级、项目级 usage 路由和项目 translation-report 零汇总响应，项目报表校验 owner/manager/reviewer 权限及当前用户 key 归属。
- [x] **Step 7: 运行测试。** analytics/Redis 聚焦测试 `18 passed`，全量测试 `156 passed`，并完成 OpenAPI 路径检查。
- [ ] **Step 8: 提交。** 按当前工作区统一提交策略暂不创建 commit。

### Task 8: 完成文档同步、全链路 HTTP 验收和部署门槛

**实现内容：** 对第 15 章进行交付前的契约、HTTP 链路和基础设施边界验收。新增 OpenAPI 覆盖测试，确认所有路径、方法、请求头、状态码和响应模型已注册；新增集成测试串联认证、项目成员、设置、术语、版本、API key、翻译任务、后台 job 和 analytics。最后同步契约文档，执行分层测试、编译和迁移检查，并把 SQLite 结果与 PostgreSQL、Redis、Celery、真实 provider、签名和部署验证结果分开记录，避免把文档或本地测试误认为生产可用性证明。

**Files:**
- Modify: `../../api-contract/docs/api.md`（只有契约发生调整时修改源文档）
- Modify: `docs/api.md`（由同步脚本生成，不手工漂移）
- Create: `tests/test_translation_workspace_openapi.py`
- Create: `tests/test_translation_workspace_http.py`
- Modify: `README.md`（新增迁移、worker、API 集成测试和边界说明）

- [x] **Step 1: 写 OpenAPI 覆盖测试。** 已覆盖第 15 章路径、方法、operation 文本、状态码、`Idempotency-Key`、响应模型、认证声明和项目级 API key 路由排除。
- [x] **Step 2: 写 HTTP 集成测试。** 使用 httpx + FastAPI + 内存 SQLite 串联登录、项目成员、版本、用户 API key、analytics 和跨项目 `404`；API key 测试使用 HTTPS base URL 验证传输保护。
- [x] **Step 3: 同步文档并检查差异。** 已运行同步脚本、文档一致性检查和 `git diff --check`，并补充 SQLite 与外部依赖边界说明。
- [x] **Step 4: 运行分层验证。** focused tests、编译和 OpenAPI 检查已通过；`aerich heads` 在当前目录因缺少 `TORTOISE_ORM` 配置无法执行，未伪造 PostgreSQL migration 验证结果。
- [x] **Step 5: 运行全套并分类结果。** 全量 SQLite 测试通过；PostgreSQL、Redis、Celery、真实 provider、TLS 终止和生产签名/部署仍单独列为未验证边界。
- [ ] **Step 6: 提交和发布检查。** 当前工作区保留 Task 2–7 的未提交改动，按用户约束暂不创建 commit 或执行发布。

## Completion Criteria

第 15 章只有在以下条件全部满足后才可称为“后端已实现”：

1. 八个任务的 focused tests 和 OpenAPI 覆盖测试通过；
2. 所有新增模型都有可回滚、可在 PostgreSQL 验证库执行的 Aerich migration；
3. 资源隔离、角色权限、revision 冲突、幂等、异步 job、secret 脱敏和 Redis fallback 均有测试证据；
4. `docs/api.md` 与契约源同步，且文档只声明已验证的运行时边界；
5. 全套测试结果、PostgreSQL/Redis/Celery/provider 状态和未验证项在交付记录中分开说明。
