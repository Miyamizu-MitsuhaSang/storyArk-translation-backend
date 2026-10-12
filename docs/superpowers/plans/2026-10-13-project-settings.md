# 项目级 Settings API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为项目增加独立的工作流 settings 资源、API、前端适配器和同步后的 API 文档，同时保持用户级 settings 与现有 translation-settings 的职责分离。

**Architecture:** 新增一对一 ProjectSettings ORM 模型和 project-settings API 模块。读取复用项目成员可见性，写入只允许 owner/manager；服务层负责默认记录、项目语言校验和 revision 并发控制。现有 auth/me/settings 与 projects/{project_id}/translation-settings 不改路径、不共用 schema。

**Tech Stack:** FastAPI、Tortoise ORM、Pydantic v2、PostgreSQL/SQLite 测试库、pytest/httpx、React/TypeScript、Vitest、仓库 API contract 同步脚本。

**Spec:** docs/superpowers/specs/2026-10-13-project-settings-design.md

## Global Constraints

- 用户级 settings 只表示账户外观和界面语言；不得接收或写入 project_id。
- 项目级 settings 使用显式类型字段；default_model 只保存模型 ID，不保存 API key 或明文凭据。
- 所有项目数据必须按 project_id 隔离；非成员返回项目不可见 404，无写权限成员返回 403。
- PATCH 只修改请求中出现的字段；空 PATCH 返回当前对象且不增加 revision。
- revision 兼容请求体和 If-Match，冲突返回 409 VERSION_CONFLICT。
- 保留当前工作区已有改动，不执行 reset、clean、checkout 或覆盖无关文件。
- API 文档只修改 ../../api-contract/docs/api.md，然后使用 ../../scripts/sync-api-docs.sh 同步四个副本。
- 使用 uv run pytest 验证后端；前端使用仓库既有测试和构建命令；真实 PostgreSQL、Redis、Celery、AI provider 和部署验证单独报告。

## 文件与接口总览

- Create: app/models/project_settings.py，导出 ProjectSettings。
- Modify: app/models/project.py、app/models/__init__.py，增加项目反向关系和模型导出。
- Create: migrations/models/18_20261013_add_project_settings.py。
- Create: app/application/project/settings/__init__.py、schemas.py、service.py。
- Create: app/api/modules/project/settings/__init__.py、dependencies.py、routes.py。
- Modify: app/api/router.py、main.py。
- Test: tests/test_project_settings_service.py、tests/test_project_settings_api.py、tests/test_project_settings_contract.py。
- Modify: ../../api-contract/docs/api.md；同步生成 docs/api.md、../../docs/api.md、../storyark_frontend/docs/api.md。
- Modify: ../storyark_frontend/src/domain/types.ts、src/data/adapter.ts、src/data/localAdapter.ts、src/data/remoteAdapter.ts。
- Test: ../storyark_frontend/src/data/remoteAdapter.test.ts 或仓库现有的等价 adapter 测试文件。

### Task 1: 模型与迁移

**Files:**
- Create: app/models/project_settings.py
- Modify: app/models/project.py
- Modify: app/models/__init__.py
- Create: migrations/models/18_20261013_add_project_settings.py
- Test: tests/test_project_settings_service.py

**Interfaces:**
- ProjectSettings.project 是一对一项目外键。
- ProjectSettings 暴露 default_source_language、default_target_language、terminology_enabled、translation_memory_enabled、default_model、quality_threshold、revision。

- [ ] Step 1: 写失败测试，创建项目设置后断言默认值为 terminology_enabled=true、translation_memory_enabled=true、quality_threshold=0.7、revision=1，并断言同一 project_id 第二次创建触发 IntegrityError。
- [ ] Step 2: 运行 uv run pytest tests/test_project_settings_service.py::test_project_settings_model_has_defaults_and_one_to_one -q，确认因模型或表不存在而失败。
- [ ] Step 3: 使用 TimestampedModel 和 OneToOneField(models.Project, on_delete=CASCADE) 实现模型；quality_threshold 使用 DecimalField(max_digits=4, decimal_places=3, default=0.7)；迁移增加项目外键、唯一约束、0 <= quality_threshold <= 1、revision >= 1 和 downgrade。
- [ ] Step 4: 重跑同一测试，确认通过。
- [ ] Step 5: 运行 rg -n "project_settings|quality_threshold|revision" migrations/models/18_20261013_add_project_settings.py，确认迁移包含表、约束和回滚。

### Task 2: Service 与 schema

**Files:**
- Create: app/application/project/settings/__init__.py
- Create: app/application/project/settings/schemas.py
- Create: app/application/project/settings/service.py
- Modify: tests/test_project_settings_service.py

**Interfaces:**
- ProjectSettingsService.get(user: User, project_id: UUID) -> ProjectSettingsResponse
- ProjectSettingsService.update(user: User, project_id: UUID, request: ProjectSettingsUpdateRequest, expected_revision: int | None) -> ProjectSettingsResponse
- ProjectSettingsError 暴露 status_code、code、details。

- [ ] Step 1: 写失败测试：成员首次读取创建默认记录；owner 可更新 quality_threshold 并递增 revision；viewer 更新抛出 403；不属于项目的语言抛出 422；旧 revision 抛出 409；只更新一个字段时其他字段保持不变。
- [ ] Step 2: 运行 uv run pytest tests/test_project_settings_service.py -q，确认因 schema/service 缺失而失败。
- [ ] Step 3: 实现 response/request schemas。quality_threshold 限制 0..1，default_model 限制最大长度 160，语言限制最大长度 16；使用 require_project_member 读取和 require_project_role(owner/manager) 写入；首次读取 get_or_create 默认记录。
- [ ] Step 4: 实现更新规则：使用 model_dump(exclude_unset=True, exclude={"revision"})；语言字段必须成对出现或都为空，并且属于项目已配置语言；空 PATCH 直接返回当前记录；成功后 revision 加一；冲突返回 VERSION_CONFLICT。
- [ ] Step 5: 重跑 uv run pytest tests/test_project_settings_service.py -q，确认通过。

### Task 3: 独立 API 路由和权限

**Files:**
- Create: app/api/modules/project/settings/__init__.py
- Create: app/api/modules/project/settings/dependencies.py
- Create: app/api/modules/project/settings/routes.py
- Modify: app/api/router.py
- Modify: main.py
- Create: tests/test_project_settings_api.py
- Create: tests/test_project_settings_contract.py

**Interfaces:**
- GET /api/v1/projects/{project_id}/settings，tag project-settings。
- PATCH /api/v1/projects/{project_id}/settings，支持 body revision 和 If-Match。
- register_project_settings_exception_handler(app)。

- [ ] Step 1: 写失败 OpenAPI 测试：路径存在且 GET/ PATCH 都有 project-settings tag；独立 router 本身不暴露 auth/me/settings 或 translation-settings。
- [ ] Step 2: 运行 uv run pytest tests/test_project_settings_contract.py -q，确认 router 尚未存在而失败。
- [ ] Step 3: 实现路由，只处理路径参数、认证依赖、expected_revision、response_model 和异常映射；服务负责 ORM 和业务规则。注册到 app/api/router.py，并在 main.py 注册异常处理器。
- [ ] Step 4: HTTP 测试建立 owner、viewer、outsider：未登录 401；owner GET/PATCH 200；viewer GET 200/PATCH 403；outsider 404；错误 revision 409；非法 quality_threshold 422；If-Match 路径遵循现有 expected_revision 行为。
- [ ] Step 5: 运行 uv run pytest tests/test_project_settings_api.py tests/test_project_settings_contract.py tests/test_user_settings_api.py tests/test_translation_settings_api.py -q，确认新旧设置路由均通过。

### Task 4: API contract 与文档同步

**Files:**
- Modify: ../../api-contract/docs/api.md
- Generated sync: docs/api.md
- Generated sync: ../../docs/api.md
- Generated sync: ../storyark_frontend/docs/api.md
- Modify: ../../scripts/check-api-docs.sh（仅在 required_paths 缺少新路径时）

- [ ] Step 1: 在契约源中新增独立章节“项目级 Settings API”，单独描述 GET/PATCH /projects/{project_id}/settings、字段、默认值、权限、revision、错误码，并明确它不属于 auth/me/settings 或 translation-settings。
- [ ] Step 2: 从仓库根目录运行 ./scripts/sync-api-docs.sh，确认四个文档副本由契约源生成。
- [ ] Step 3: 如检查脚本没有新路径，加入 /projects/{project_id}/settings；运行 ./scripts/check-api-docs.sh，确认四个副本一致且路径存在。
- [ ] Step 4: 运行 git diff --check -- ../../api-contract/docs/api.md docs/api.md ../../docs/api.md ../storyark_frontend/docs/api.md，确认无空白错误且只有预期章节变化。

### Task 5: 前端类型和 adapter

**Files:**
- Modify: ../storyark_frontend/src/domain/types.ts
- Modify: ../storyark_frontend/src/data/adapter.ts
- Modify: ../storyark_frontend/src/data/localAdapter.ts
- Modify: ../storyark_frontend/src/data/remoteAdapter.ts
- Test: ../storyark_frontend/src/data/remoteAdapter.test.ts 或现有等价测试文件

**Interfaces:**
- ProjectSettings 包含 projectId、defaultSourceLanguage、defaultTargetLanguage、terminologyEnabled、translationMemoryEnabled、defaultModel、qualityThreshold、revision、updatedAt。
- ProjectSettingsUpdate 包含上述可写字段和可选 revision。
- DataAdapter 增加 getProjectSettings(): Promise<ProjectSettings> 和 updateProjectSettings(input: ProjectSettingsUpdate): Promise<ProjectSettings>。

- [ ] Step 1: 写失败 adapter 测试：getProjectSettings 调用 /projects/project-1/settings；updateProjectSettings PATCH 同路径并发送当前 revision；测试断言不会调用 /auth/me/settings 或 /translation-settings。
- [ ] Step 2: 运行 cd ../storyark_frontend && npm test -- --run <adapter-test-file>，确认方法不存在而失败。
- [ ] Step 3: remoteAdapter 使用当前 project ID 调用独立 settings endpoint，完成 snake_case 到 camelCase 映射和 revision 回传；localAdapter 增加与后端一致的默认 project settings，并按当前项目保存。
- [ ] Step 4: 运行前端 adapter 测试和 npm run build，确认测试及 TypeScript 编译通过。

### Task 6: 完整验证

**Files:**
- 仅在验证发现缺陷时修改上述文件。

- [ ] Step 1: 运行后端 focused suite：uv run pytest tests/test_project_settings_service.py tests/test_project_settings_api.py tests/test_project_settings_contract.py tests/test_user_settings_api.py tests/test_translation_settings_api.py -q。
- [ ] Step 2: 运行 uv run pytest -q；记录并单独报告外部基础设施相关失败。
- [ ] Step 3: 运行前端 npm test -- --run 和 npm run build。
- [ ] Step 4: 运行 OpenAPI 检查：uv run python -c "from main import app; p=app.openapi()['paths']; assert '/api/v1/projects/{project_id}/settings' in p; assert 'project-settings' in p['/api/v1/projects/{project_id}/settings']['get']['tags']"。
- [ ] Step 5: 运行 ./scripts/check-api-docs.sh、git status --short、git diff --stat、git diff --check，确认范围只包含本任务文件，且既有无关改动仍保留。
