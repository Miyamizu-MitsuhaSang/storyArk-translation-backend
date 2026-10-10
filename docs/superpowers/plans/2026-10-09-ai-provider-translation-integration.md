# AI Provider 翻译接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过 `model_type -> registry -> invoker` 接入 provider 调用，并在 CAT Workbench 实现单片段 AI 翻译、在 CAT Workflow 实现 xlsx/csv 批量翻译与人工复核衔接。

**Architecture:** 建立不依赖框架和厂商 SDK 的翻译 contracts；application service 负责项目 binding、凭据解密、重试、错误归一化和 usage 写入；infrastructure registry 只接受服务端注册的 `model_type` 并选择 invoker。Workbench 与 Workflow 共用同一个 `AiTranslationService`，表格批量任务通过现有 `BackgroundJob`/Celery 生命周期执行，并将可复核结果映射回 `DocumentSegment` 草稿。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、Tortoise ORM、httpx/现有 OpenAI SDK、Celery/Redis、openpyxl、csv、pytest、uv。

**Spec:** `docs/superpowers/specs/2026-10-08-ai-provider-translation-integration-design.md`

## Global Constraints

- 上层只传服务端支持的 `model_type`；不得让用户传任意模块路径、类名或函数名。
- CAT Workbench 负责单片段 AI 翻译/建议；CAT Workflow 负责表格批量任务和人工审核衔接；两者共享同一 application service。
- API secret 只在受限调用栈短暂解密；不能写入响应、日志、审计、任务结果、提示词记录或导出。
- 不保存完整 prompt、completion 或原始表格内容到数据库；provider 使用量以 `AIUsageRecord` 为事实来源。
- AI 结果只进入 `draft`/`translated`；禁止直接进入 `in_review`、`approved` 或 `confirmed`。
- `xlsx` 保留工作簿/工作表/非翻译列/单元格格式；CSV 只承诺保留表头、列序和未修改数据。
- 复用 `BackgroundJob`；本计划的 `TranslationTask` 是项目中 translation-task API 的唯一资源，不得再建平行批量任务模型。
- SQLite、OpenAPI 注册和文档同步不证明 PostgreSQL、Redis、Celery 或真实 provider 部署可用。

## Baseline And File Map

当前已有并复用：

- `app/application/auth/api_key/service.py`：API key AES-256-GCM 加解密和脱敏响应。
- `app/application/project/api_key/service.py`、`app/repositories/api_key.py`：项目 binding 和所属关系查询。
- `app/models/ai_usage.py`、`app/repositories/usage.py`：provider 用量明细基础模型和 repository。
- `app/models/jobs.py`、`app/tasks/celery_app.py`：后台任务 lease、重试、取消和队列入口。
- `app/models/document.py`、`app/infrastructure/document/storage.py`、`app/application/project/document/`：项目文件、片段和本地文件存储。
- `app/application/project/cat/workbench/service.py`：TM、术语和世界观建议；`llm` 目前仅返回 `LLM_PROVIDER_NOT_IMPLEMENTED`。
- `app/application/project/cat/workflow/service.py`：现有 CAT 审核状态机，不调用 provider。

新增模块职责：

| 文件/目录 | 职责 |
| --- | --- |
| `app/domain/ai_translation/contracts.py` | 纯 Python 请求、结果、上下文、usage 和 provider 错误类型 |
| `app/domain/ai_translation/policies.py` | 文本/语言/模型类型输入限制和 provider 错误重试策略 |
| `app/infrastructure/ai_provider/protocol.py` | `ModelInvoker` 协议 |
| `app/infrastructure/ai_provider/registry.py` | 受控 `model_type -> invoker factory` 注册、解析和 provider 对应关系 |
| `app/infrastructure/ai_provider/openai_chat.py` | 首个真实 OpenAI Chat Completions invoker，懒加载 SDK |
| `app/application/ai_translation/service.py` | binding 检查、解密、调用、重试、usage 事实写入 |
| `app/application/project/cat/workbench/ai_translation.py` | CAT 上下文装配和候选/草稿工作流编排 |
| `app/infrastructure/spreadsheet/csv_adapter.py` | CSV 读取、列映射和写回 |
| `app/infrastructure/spreadsheet/xlsx_adapter.py` | XLSX 读取、列映射、样式保留和写回 |
| `app/application/project/cat/workflow/translation_task/` | 批量任务 schemas、service 和状态/进度查询 |
| `app/tasks/translation_tasks.py` | translation task 的 Celery worker 入口 |

批量任务模型和 `GET/POST /projects/{project_id}/translation-tasks` 路由与 `docs/superpowers/plans/2026-10-08-translation-workspace-api-additions.md` 中的 Task 6 是同一资源。执行本计划时将该计划 Task 6 合并/替换为本计划 Task 5，不得重复建立任务模型或相同路由。

---

### Task 1: 建立翻译 contracts、model registry 和 fake invoker

**Files:**
- Create: `app/domain/ai_translation/__init__.py`
- Create: `app/domain/ai_translation/contracts.py`
- Create: `app/domain/ai_translation/errors.py`
- Create: `app/domain/ai_translation/policies.py`
- Create: `app/infrastructure/ai_provider/__init__.py`
- Create: `app/infrastructure/ai_provider/protocol.py`
- Create: `app/infrastructure/ai_provider/registry.py`
- Create: `app/infrastructure/ai_provider/fake.py`
- Test: `tests/test_ai_translation_contracts.py`
- Test: `tests/test_model_invoker_registry.py`

**Interfaces:**
- Produces `TranslationRequest(text, source_language, target_language, model_type, model, context, temperature, max_tokens, request_id)`。
- Produces `TranslationResult(text, provider, model_type, model, provider_request_id, usage, latency_ms, finish_reason, warnings)`。
- Produces `ModelInvoker.translate(request, *, api_key) -> TranslationResult`。
- Produces `ModelInvokerRegistry.resolve(model_type) -> ModelInvoker` 和 `ModelInvokerRegistry.provider_for(model_type) -> str`。
- `fake.echo` 仅供测试，不得列入生产默认 registry。

- [ ] **Step 1: 写 contracts 和 policy 失败测试。** 覆盖必填文本、source/target 不同、文本长度边界、temperature 范围、`UsageSnapshot` 非负计数，以及错误是否可重试的分类。
- [ ] **Step 2: 运行测试确认失败。** `uv run pytest tests/test_ai_translation_contracts.py -q`；预期因 contracts 尚未定义失败。
- [ ] **Step 3: 实现 domain contracts。** 使用标准 dataclass 或 Pydantic-free dataclass；request 的 `context` 只包含受控前后文、术语、世界观和风格字段，禁止凭据字段。
- [ ] **Step 4: 实现 registry。** registry 构造时接收不可变 mapping；未知 key 抛 `ModelTypeUnsupportedError(code="MODEL_TYPE_UNSUPPORTED")`；禁止动态 import 和 user-provided callable path。
- [ ] **Step 5: 加入 fake invoker 并测试 registry。** fake 通过 constructor 注入固定返回值或异常；覆盖匹配类型选择、未知类型失败和多实例隔离。运行 `uv run pytest tests/test_ai_translation_contracts.py tests/test_model_invoker_registry.py -q`。
- [ ] **Step 6: 提交。** `git add app/domain/ai_translation app/infrastructure/ai_provider tests/test_ai_translation_contracts.py tests/test_model_invoker_registry.py && git commit -m "feat: add AI translation provider contracts"`。

### Task 2: 实现统一 AiTranslationService 和 usage 写入

**Files:**
- Create: `app/application/ai_translation/__init__.py`
- Create: `app/application/ai_translation/service.py`
- Create: `app/application/ai_translation/errors.py`
- Modify: `app/repositories/api_key.py`
- Modify: `app/repositories/usage.py`
- Modify: `app/application/auth/api_key/service.py`
- Test: `tests/test_ai_translation_service.py`

**Interfaces:**
- Consumes `TranslationRequest`、`ModelInvokerRegistry`、`ApiKeyService.decrypt`、`ProjectApiKeyRepository` 和 `AIUsageRepository`。
- Produces `AiTranslationService.translate(user, project_id, binding_id, request) -> TranslationResult`。
- 对 user/project/binding 不可见统一使用 404；inactive binding、key 或 provider mismatch 使用稳定 domain error。

- [ ] **Step 1: 写失败测试。** 使用 fake invoker 和内存 SQLite 覆盖成功调用、binding 不存在或不属于项目、inactive key、provider mismatch、SDK/provider 失败、超时、429/5xx 重试上限、每个实际 HTTP attempt 恰好写一条 usage record，以及 secret 不进入记录/异常/job payload。
- [ ] **Step 2: 运行测试确认失败。** `uv run pytest tests/test_ai_translation_service.py -q`。
- [ ] **Step 3: 补全 credential lookup 接口。** 在 `ApiKeyRepository` 增加通过 project binding ID 查询 binding、key owner 和 active 状态的方法；service 先校验项目可见，再取 binding；不在 API route 暴露 credential model。
- [ ] **Step 4: 实现调用编排。** registry 按 `request.model_type` 解析 invoker，验证 `provider_for(model_type) == binding.provider`，再用已有 `ApiKeyService.decrypt` 获取 secret；只在调用作用域内持有明文，不记录日志。
- [ ] **Step 5: 实现重试和 usage。** 仅对 timeout、429、明确可重试 5xx 进行最多 3 次指数退避；每个实际 provider HTTP attempt 都写一条 `AIUsageRecord`，成功/失败/超时分别使用相应状态，保留可得的部分 usage、provider request ID、耗时和稳定 error code；禁止用应用重试 ID 伪装 provider request ID。
- [ ] **Step 6: 运行测试。** `uv run pytest tests/test_ai_translation_service.py tests/test_api_key_service.py tests/test_project_api_key_security.py -q`；已有 `AIUsageRecord` 字段可承载首期明细，不为首期 registry 额外持久化 `model_type`。
- [ ] **Step 7: 提交。** `git add app/application/ai_translation app/repositories/api_key.py app/repositories/usage.py app/application/auth/api_key/service.py tests/test_ai_translation_service.py && git commit -m "feat: orchestrate AI translation calls"`。

### Task 3: 接入首个真实 adapter 和 CAT Workbench

**Files:**
- Create: `app/infrastructure/ai_provider/openai_chat.py`
- Create: `app/application/project/cat/workbench/ai_translation.py`
- Modify: `app/application/project/cat/schemas.py`
- Modify: `app/application/project/cat/workbench/service.py`
- Modify: `app/api/modules/project/cat/dependencies.py`
- Modify: `app/api/modules/project/cat/workbench/routes.py`
- Test: `tests/test_openai_chat_invoker.py`
- Test: `tests/test_cat_ai_translation.py`
- Test: `tests/test_cat_workbench_api.py`

**Interfaces:**
- `OpenAIChatInvoker(provider="openai").translate(request, *, api_key) -> TranslationResult`。
- `CatWorkbenchService.ai_translate(user, project_id, segment_id, request) -> AiTranslationResponse`。
- Existing `suggestions()` handles `providers` containing `llm` via the same injected `AiTranslationService`.

- [ ] **Step 1: 写 OpenAI adapter 失败测试。** mock SDK client，验证 model、system/user message、temperature、max tokens、API key、provider request ID 和 token usage 映射；验证鉴权、429、5xx、timeout、空 choices 和 malformed response 的错误映射。
- [ ] **Step 2: 运行 adapter 测试确认失败。** `uv run pytest tests/test_openai_chat_invoker.py -q`。
- [ ] **Step 3: 实现 OpenAI adapter。** 使用项目已有 `openai` 依赖，client 延迟创建；不在模块 import 时联网或读取凭据；将 provider exceptions 转换为 domain provider errors，不向上抛原始 response body。
- [ ] **Step 4: 扩展 suggestion schema/service。** 增加可选 `model_type`、`model` 和 `project_api_key_id` 请求字段；`llm` 未提供必要字段时返回 `MODEL_CONFIGURATION_REQUIRED`；每个片段只发起一次 LLM 调用并保存一条 `SegmentSuggestion(source="llm")`，沿用现有 `provider`/`model`/`latency_ms` 字段，不为首期另加 migration；其他建议源失败隔离。
- [ ] **Step 5: 新增单片段 AI translate schema/service。** 请求包含 model_type/model/project_api_key_id/version/lock_token/apply；验证项目成员、锁持有人和版本；`apply=false` 不修改 segment，`apply=true` 只写 target/status/workflow_state/version/change_history，不直接送审。模型调用异常响应仅包含稳定 error code。
- [ ] **Step 6: 挂载 route 和依赖。** 在 `app/api/modules/project/cat/dependencies.py` 注入同一个 `AiTranslationService` 给 Workbench；新增 `POST /projects/{project_id}/segments/{segment_id}/ai-translate`；route 只做 HTTP schema/依赖/响应映射。
- [ ] **Step 7: 运行测试。** `uv run pytest tests/test_openai_chat_invoker.py tests/test_cat_ai_translation.py tests/test_cat_workbench_api.py tests/test_cat_workflows.py -q`；检查 suggestions 原有非 LLM 返回不变，OpenAPI 只注册一条 ai-translate 路径。
- [ ] **Step 8: 提交。** `git add app/infrastructure/ai_provider/openai_chat.py app/application/project/cat app/api/modules/project/cat tests/test_openai_chat_invoker.py tests/test_cat_ai_translation.py tests/test_cat_workbench_api.py && git commit -m "feat: add CAT workbench AI translation"`。

### Task 4: 实现 CSV/XLSX 表格适配器

**Files:**
- Modify: `pyproject.toml`（新增 `openpyxl` 运行依赖）
- Modify: `uv.lock`（由 `uv lock` 更新）
- Create: `app/infrastructure/spreadsheet/__init__.py`
- Create: `app/infrastructure/spreadsheet/contracts.py`
- Create: `app/infrastructure/spreadsheet/csv_adapter.py`
- Create: `app/infrastructure/spreadsheet/xlsx_adapter.py`
- Test: `tests/test_spreadsheet_adapters.py`

**Interfaces:**
- `TableColumn(language: str, column: str)`。
- `SpreadsheetSpec(source_column: str, target_columns: list[TableColumn], sheet_names: list[str] | None, overwrite: bool)`。
- `SpreadsheetAdapter.read(content: bytes, spec: SpreadsheetSpec) -> list[SpreadsheetCell]`。
- `SpreadsheetAdapter.write(content: bytes, spec: SpreadsheetSpec, translations: dict[CellAddress, str]) -> bytes`。
- XLSX address is `(sheet_name, source_cell, target_cell)`; CSV address is `(row_number, source_column_index, target_column_index)`.

- [ ] **Step 1: 写 CSV/XLSX fixture 和失败测试。** 覆盖表头列查找、缺少/重复列、指定工作表、多目标语言、空源单元格、公式 cell 不翻译、已有 target overwrite 规则、未知列创建、CSV 列顺序保留、XLSX 样式/合并/非目标 sheet 保留、非法或超大文件拒绝。
- [ ] **Step 2: 运行测试确认失败。** `uv run pytest tests/test_spreadsheet_adapters.py -q`。
- [ ] **Step 3: 增加 openpyxl 并实现共享 contracts。** 使用 `uv add openpyxl`（需确认 pyproject diff 仅含此依赖）并定义单元格地址和输入校验错误；不要把 workbook 对象泄露给 application service。
- [ ] **Step 4: 实现 CSV adapter。** 用标准库 `csv`，保留 dialect 可推断的 delimiter、header、列序和其他值；根据目标 column 名新增列；只写入显式地址的翻译。
- [ ] **Step 5: 实现 XLSX adapter。** 用 `load_workbook(BytesIO(content))`；默认不处理公式和空源格；目标列缺失则创建；目标 cell 复制源 cell 的 `_style`、number format、alignment、protection；保存时保留所有未修改 sheet。宏工作簿不承诺保留 VBA，遇到 `.xlsm` 明确拒绝。
- [ ] **Step 6: 运行测试并提交。** `uv run pytest tests/test_spreadsheet_adapters.py -q`；`git diff --check`；提交 `git add pyproject.toml uv.lock app/infrastructure/spreadsheet tests/test_spreadsheet_adapters.py && git commit -m "feat: add spreadsheet translation adapters"`。

### Task 5: 接入 CAT Workflow 表格批量翻译任务

**Files:**
- Modify: `app/models/translation_task.py`（与翻译工作区 API 计划 Task 6 合并；唯一 `TranslationTask` 和文件/单元格映射模型）
- Modify: `app/models/__init__.py`（由翻译工作区 API 计划注册一次）
- Create: `app/application/project/cat/workflow/translation_task/__init__.py`
- Create: `app/application/project/cat/workflow/translation_task/schemas.py`
- Create: `app/application/project/cat/workflow/translation_task/service.py`
- Modify: `app/application/project/cat/workflow/service.py`
- Modify: `app/api/modules/project/cat/workflow/routes.py`
- Modify: `app/api/modules/project/cat/dependencies.py`
- Create: `app/tasks/translation_tasks.py`
- Modify: `app/application/jobs/service.py`
- Modify: `app/application/project/api_key/service.py`
- Modify: `migrations/models/14_20261008_add_translation_tasks.py`（合并到翻译工作区 API 计划 Task 6 的迁移，不另建同功能 migration）
- Test: `tests/test_translation_tasks_service.py`
- Test: `tests/test_translation_tasks_worker.py`
- Test: `tests/test_translation_tasks_api.py`
- Test: `tests/test_project_api_key_security.py`

**Interfaces:**
- `TranslationTaskService.create(user, project_id, request, idempotency_key) -> TranslationTaskResponse`。
- `TranslationTaskService.list(user, project_id, query) -> TranslationTaskPage`。
- `TranslationTaskService.get(user, project_id, task_id) -> TranslationTaskResponse`。
- `TranslationTaskService.cancel(user, project_id, task_id) -> TranslationTaskResponse`。
- `TranslationTaskWorker.run(task_id) -> dict[str, object]`。
- CAT Workflow 提供审核入口；翻译任务 `review` 是批处理阶段状态，segment 继续处于 `draft/translated`，审核必须逐片段走现有 `submit_review/approve/confirm`。

- [x] **Step 1: 写失败测试。** 覆盖 CSV/XLSX 文件类型、source/target column 映射、语言不重复、project role、idempotency、任务列表归属、取消、活动任务引用的用户级 key 不能停用/删除、所有响应字段不含 secret。
- [x] **Step 2: 运行测试确认失败。** 已运行 Task 5 聚焦测试并确认缺失表格 contracts/adapter 时红灯。
- [x] **Step 3: 合并任务模型和迁移。** 在唯一 `TranslationTask`/`TranslationTaskFile` 上加入 `model_type`、model、列映射、输出文件引用、BackgroundJob 快照和 cell 进度字段；不保存原始表格内容或 secret。任务状态为 `queued -> translating -> review`，另有 `failed/cancelled`；`review` 是批处理阶段，不是 CAT segment workflow state。
- [x] **Step 4: 实现创建/列表/详情/取消 application service。** 创建时验证项目角色、项目文件、CSV/XLSX 格式、table columns、用户级 API key 和幂等性；响应只带脱敏 provider/model/key 元数据；`BackgroundJob` 负责执行 lease 和 Celery 生命周期。
- [x] **Step 5: 实现 worker。** claim `translation_task` 对应 BackgroundJob；用 DocumentStorage 读取原文件、adapter 解析单元格，调用注入的 invoker；逐 cell 更新进度；写入输出文件并映射为 `DocumentSegment` 的 `translated/draft`；完成后进入 `review`，不自动 approve/confirm。
- [x] **Step 6: 实现幂等重试、进度和失败边界。** 支持取消检查、进度记录、provider 异常稳定错误码和 BackgroundJob 终态；响应、任务结果和错误均不包含 secret 或内部存储路径。
- [x] **Step 7: 复用审核工作流并保护 binding。** 任务输出仅对项目成员可下载，服务端根据任务 UUID 解析内部 storage key；用户级 API key 被 queued/translating 任务引用时不能删除或停用。
- [x] **Step 8: 测试并验证。** 已通过 `tests/test_translation_tasks_service.py`、`tests/test_translation_tasks_worker.py`、`tests/test_translation_tasks_api.py`、`tests/test_project_api_key_security.py`、`tests/test_jobs_service.py` 及 spreadsheet adapter 测试；全量测试保持通过。

### Task 6: 同步 API 契约、文档和集成验证

**Files:**
- Modify: `../../api-contract/docs/api.md`
- Sync: `docs/api.md` 和 `../../src/translation_frontend/docs/api.md`（仅通过仓库同步脚本生成）
- Modify: `README.md`
- Modify: `docs/database.md`
- Test: `tests/test_ai_translation_api_contract.py`
- Test: `tests/test_translation_tasks_api.py`

**Interfaces:**
- API 文档公开 `model_type`、model、binding 引用、错误码、列映射、覆盖策略、任务状态和输出文件访问规则。
- 不把尚未实现的 Anthropic/Google/custom adapter 标成已支持；首期只声明实际实现的 `openai.chat` 和测试用 fake。

- [ ] **Step 1: 补充 API contract。** 在 CAT suggestions、单片段 `ai-translate`、translation tasks 和 provider/model type 章节记录 request/response/error schema；注明 `review` 任务不等于 segment 已审核。
- [ ] **Step 2: 补充数据库/README。** 更新 AI provider adapter、可选 provider SDK、openpyxl、celery worker 配置和 secret 安全边界；明确真实调用需要用户提供可用 key 和网络服务。
- [ ] **Step 3: 同步 API 文档。** 从 `translate-platform` 根目录运行 `./scripts/sync-api-docs.sh`；再运行 `./scripts/check-api-docs.sh`，不手工编辑同步副本。
- [ ] **Step 4: 验证静态和 focused tests。** 运行 `uv run pytest tests/test_ai_translation_contracts.py tests/test_model_invoker_registry.py tests/test_ai_translation_service.py tests/test_openai_chat_invoker.py tests/test_cat_ai_translation.py tests/test_cat_workbench_api.py tests/test_spreadsheet_adapters.py tests/test_translation_tasks_service.py tests/test_translation_tasks_worker.py tests/test_translation_tasks_api.py -q`、`uv run python -m compileall -q app models migrations`、`git diff --check`。
- [ ] **Step 5: 验证完整套件和 OpenAPI。** 运行 `uv run pytest -q`；检查 `/openapi.json` 中新增端点、请求字段和响应模型；将代码失败与 PostgreSQL/Redis/Celery/provider 未启动分别记录。
- [ ] **Step 6: 最终提交。** 检查 `git status --short` 和 staged paths，只提交本计划范围文件；运行 `git diff --cached --check` 后提交 `git commit -m "docs: document AI translation provider integration"`。

## Completion Criteria

1. Workbench 和 Workflow 都只向 `AiTranslationService` 传 `model_type`，不含厂商条件分支或 SDK import。
2. Registry 只能解析服务端 allowlist；未知类型、SDK 未安装、key/provider 不匹配得到稳定错误。
3. fake invoker 能通过 API、application、Workbench、Workflow、表格 worker 全链路测试。
4. XLSX/CSV 只修改指定目标列；XLSX 样式和其他 sheet/列保留，CSV 行列顺序保留。
5. 批量结果处于人工可复核草稿状态，现有工作流仍控制审核、确认和 TM 写入。
6. 每次 provider 调用都有 usage 明细，secret/prompt/completion 不出现在持久化任务结果或日志。
7. 文档同步、focused tests、完整测试和外部基础设施验证分别报告，不混为一个“通过”。
