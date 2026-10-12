# AI Provider 文本翻译完整接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在只支持文本输入输出的边界内，完成多厂商 provider catalog、兼容协议 adapter、原生协议 adapter、专属文本参数、CAT 接入、usage/错误/重试和验收文档。

**Architecture:** API 和 CAT 业务只依赖 `AiTranslationService` 与受控 `ProviderCatalog`；domain contract 不依赖 SDK；infrastructure adapter 负责各厂商请求和响应映射。OpenAI、DeepSeek、Qwen、Kimi、Doubao、Zhipu、MiniMax、Groq、Mistral 复用兼容协议基础，Anthropic 与 Google 使用原生文本 adapter。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、Tortoise ORM、OpenAI SDK、httpx、Celery/Redis、pytest、uv。

**Spec:** `docs/superpowers/specs/2026-10-12-ai-provider-text-complete-design.md`

## Global Constraints

- 只实现文本输入输出；所有 registration 的 `supports_multimodal` 必须为 `false`。
- domain contract 不导入 FastAPI、Tortoise、Celery、厂商 SDK 或 HTTP 客户端。
- 用户请求只能选择服务端 allowlist 中的 `model_type` 和 `model`，不能覆盖 endpoint、headers 或 SDK 类名。
- API secret 只在调用栈内短暂解密；不写入日志、任务结果、审计、usage、prompt 或 completion。
- `AIUsageRecord` 是 provider 用量事实来源；每个实际 provider attempt 恰好写一条明细。
- 只有 timeout、明确限流和明确可重试 5xx 允许有限重试；认证、参数、模型和内容安全错误不重试。
- AI 译文只能进入 `draft`/`translated`，不得自动进入 `in_review`、`approved` 或 `confirmed`。
- 每个任务使用 TDD：先写失败测试，确认红灯，再写最小实现，最后运行 focused 和完整测试。
- 不覆盖当前工作区 settings 未提交改动；每次提交只包含本计划范围文件。

---

### Task 1: 完善文本领域 contract 和 provider options

**Files:**
- Modify: `app/domain/ai_translation/contracts.py`
- Modify: `app/domain/ai_translation/errors.py`
- Create: `app/domain/ai_translation/options.py`
- Modify: `app/infrastructure/ai_provider/protocol.py`
- Test: `tests/test_ai_translation_contracts.py`

**Interfaces:**
- `TranslationContext`：只允许结构化文本上下文。
- `ProviderTextOptions`：基础字段 `temperature: float | None`、`max_tokens: int | None`、`stop: tuple[str, ...]`。
- `TranslationRequest(..., context: TranslationContext, options: ProviderTextOptions)`。
- `ProviderCapabilities`：增加 `supports_system_message`、`supports_temperature`、`supports_max_tokens`、`supports_stop`、`supports_reasoning`、`supports_cached_tokens`、`supports_structured_text`、`supports_multimodal`。

- [ ] 写失败测试：非法 secret context、负 token、空 stop、超范围参数、multimodal option 被拒绝、provider 不支持 option 时返回 `MODEL_OPTION_UNSUPPORTED`。
- [ ] 运行 `uv run pytest tests/test_ai_translation_contracts.py -q`，确认因新类型和校验缺失失败。
- [ ] 用不可变 dataclass 实现 contract/options，保持 domain 不依赖 Pydantic；API 层负责把 Pydantic 输入转换成这些对象。
- [ ] 扩展稳定错误码：`PROVIDER_NOT_CONFIGURED`、`MODEL_OPTION_UNSUPPORTED`、`CONTENT_SAFETY_REJECTED`、`PROVIDER_RESPONSE_INVALID`。
- [ ] 运行 focused tests、`compileall` 和 `git diff --check`。
- [ ] 提交 `feat: define text provider contracts`。

### Task 2: 建立 ProviderCatalog 和能力查询 API

**Files:**
- Create: `app/infrastructure/ai_provider/catalog.py`
- Modify: `app/infrastructure/ai_provider/registry.py`
- Modify: `app/infrastructure/ai_provider/__init__.py`
- Create: `app/application/ai_translation/catalog_service.py`
- Create: `app/api/modules/ai/__init__.py`
- Create: `app/api/modules/ai/routes.py`
- Modify: `app/api/modules/router.py`
- Test: `tests/test_ai_provider_catalog.py`
- Test: `tests/test_ai_provider_catalog_api.py`

**Interfaces:**
- `ProviderCatalogEntry(model_type, provider, adapter_kind, enabled, models, capabilities, credential_provider)`。
- `ProviderCatalog.list_public() -> list[ProviderCatalogEntry]`。
- `ModelInvokerRegistry.registration_for(model_type) -> ModelRegistration`。
- `GET /api/v1/ai/providers -> ProviderCatalogResponse`。

- [ ] 写失败测试：未启用 provider 不出现在列表；endpoint/secret 不出现在响应；model_type、模型和 capabilities 稳定返回；未知 model_type 返回 `MODEL_TYPE_UNSUPPORTED`。
- [ ] 运行 focused tests 确认红灯。
- [ ] 将当前 registry 改为由 catalog registration 构建，同时保留现有 tuple 注册兼容层，禁止动态 import。
- [ ] 增加 route、认证依赖和中文 description；只返回 provider、model_type、模型和能力。
- [ ] 运行 OpenAPI 检查，确认路由 description 和响应 schema 完整。
- [ ] 提交 `feat: expose text provider catalog`。

### Task 3: 完成 OpenAI-compatible 文本 provider 族

**Files:**
- Modify: `app/core/config.py`
- Modify: `env/.env.app`
- Modify: `app/infrastructure/ai_provider/openai_compatible.py`
- Modify: `app/infrastructure/ai_provider/registry.py`
- Create: `app/infrastructure/ai_provider/provider_profiles.py`
- Test: `tests/test_openai_compatible_providers.py`
- Test: `tests/test_provider_error_mapping.py`

**Interfaces:**
- `CompatibleProviderProfile(provider, model_type, base_url_setting, model_allowlist_setting, usage_mapper, error_mapper, capabilities)`。
- `OpenAICompatibleInvoker(profile, client_factory=None).translate(request, api_key=...)`。
- Initial registrations: `openai.chat`, `deepseek.chat`, `qwen.chat`, `kimi.chat`, `doubao.chat`, `zhipu.chat`, `minimax.chat`, `groq.chat`, `mistral.chat`。

- [ ] 为每个 provider 写 mock HTTP/SDK 测试：endpoint 固定来自配置、model 传递、文本消息、usage、request id、错误码和 multimodal=false。
- [ ] 运行测试确认新 provider registration 尚不存在而失败。
- [ ] 将兼容 adapter 的 response/usage/error 映射抽为 profile；为 provider 设置开关、endpoint 和逗号分隔模型白名单。
- [ ] 对 DeepSeek reasoning、Qwen thinking 等不兼容字段先返回 `MODEL_OPTION_UNSUPPORTED`，不要静默转发。
- [ ] 检查 API Key provider 与 registration provider 的严格匹配。
- [ ] 运行所有 provider focused tests、完整测试、compileall 和 diff check。
- [ ] 提交 `feat: support compatible text providers`。

### Task 4: 接入 Anthropic 和 Google 原生文本协议

**Files:**
- Create: `app/infrastructure/ai_provider/anthropic_messages.py`
- Create: `app/infrastructure/ai_provider/google_generative.py`
- Modify: `app/infrastructure/ai_provider/registry.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `app/core/config.py`
- Modify: `env/.env.app`
- Test: `tests/test_anthropic_messages_invoker.py`
- Test: `tests/test_google_generative_invoker.py`

**Interfaces:**
- `AnthropicMessagesInvoker.translate(request, api_key=...) -> TranslationResult`。
- `GoogleGenerativeInvoker.translate(request, api_key=...) -> TranslationResult`。
- Registrations: `anthropic.messages`、`google.gemini`。

- [ ] 写 mock HTTP tests：文本 system/message 结构、model、token usage、stop/finish reason、安全拒绝和 malformed response。
- [ ] 运行 focused tests 确认 adapter 缺失导致失败。
- [ ] 使用官方 SDK 或受控 httpx client，实现原生文本 payload；不得发送图片、音频、视频或任意 content part。
- [ ] 将 Anthropic/Google usage 和错误映射到统一 contract。
- [ ] 增加依赖和配置，未启用时不注册 provider。
- [ ] 运行 focused、完整测试和 OpenAPI 检查。
- [ ] 提交 `feat: add native text provider adapters`。

### Task 5: 实现厂商专属文本 options 和 reasoning usage

**Files:**
- Modify: `app/domain/ai_translation/options.py`
- Create: `app/application/ai_translation/options_service.py`
- Modify: `app/infrastructure/ai_provider/provider_profiles.py`
- Modify: `app/infrastructure/ai_provider/openai_compatible.py`
- Modify: `app/infrastructure/ai_provider/anthropic_messages.py`
- Modify: `app/infrastructure/ai_provider/google_generative.py`
- Modify: `app/application/ai_translation/service.py`
- Test: `tests/test_provider_text_options.py`
- Test: `tests/test_provider_usage_mapping.py`

**Interfaces:**
- `ProviderTextOptions` 的 provider-specific typed variants：`DeepSeekTextOptions`、`QwenTextOptions`、`AnthropicTextOptions`、`GoogleTextOptions`。
- `validate_options(registration, options) -> None`。
- `map_usage(response) -> UsageSnapshot`。

- [ ] 写失败测试：DeepSeek reasoning、Qwen thinking、Anthropic extended thinking、Google safety/generation settings 的合法/非法组合，以及 reasoning/cached token 映射。
- [ ] 运行测试确认 options mapper 尚未支持这些能力而失败。
- [ ] 只实现已通过 provider 文档和 mock response 验证的文本字段；所有多模态字段拒绝。
- [ ] 将专属参数在 adapter 内映射，application service 不加入厂商条件分支。
- [ ] 对 provider 不返回的 usage 字段填 0，不估算计费 token。
- [ ] 更新错误映射、usage repository 测试和 analytics fixture。
- [ ] 提交 `feat: map provider-specific text capabilities`。

### Task 6: 完善 AiTranslationService 的重试、usage 和审计边界

**Files:**
- Create: `app/application/ai_translation/retry_policy.py`
- Modify: `app/application/ai_translation/service.py`
- Modify: `app/repositories/usage.py`
- Modify: `app/core/config.py`
- Modify: `env/.env.app`
- Test: `tests/test_ai_translation_retry_policy.py`
- Test: `tests/test_ai_translation_service.py`

**Interfaces:**
- `RetryPolicy(max_attempts, base_delay_seconds, max_delay_seconds)`。
- `AiTranslationService.translate(...)`：每次实际 provider attempt 写一条 usage。

- [ ] 写失败测试：timeout/429/可重试 5xx 最多 3 次；认证、模型、参数和 content safety 不重试；每次 attempt 的状态、request id、部分 usage、latency 和 error code 正确保存。
- [ ] 运行测试确认当前 service 没有重试和精细错误记录而失败。
- [ ] 实现有限指数退避；测试中注入 clock/sleep，不真实等待。
- [ ] 确保 secret、prompt、completion、原始 response 不进入 usage、日志、审计和 job payload。
- [ ] 运行 provider/service/analytics focused tests 和完整测试。
- [ ] 提交 `feat: harden provider retries and usage accounting`。

### Task 7: 接入 CAT Workbench 和 Workflow 的文本能力

**Files:**
- Modify: `app/application/project/cat/workbench/service.py`
- Modify: `app/application/project/cat/workflow/service.py`
- Modify: `app/api/modules/project/cat/workbench/routes.py`
- Modify: `app/api/modules/project/cat/workflow/routes.py`
- Modify: `app/tasks/translation_tasks.py`
- Modify: `app/application/project/cat/schemas.py`
- Test: `tests/test_cat_ai_translation.py`
- Test: `tests/test_translation_tasks_worker.py`
- Test: `tests/test_cat_workbench_api.py`

**Interfaces:**
- Workbench 调用 `AiTranslationService.translate`，只接收 `model_type/model/options`。
- Workflow worker 调用相同 service，结果只写 `draft/translated`。

- [ ] 写失败测试：不同 provider 的单 segment 和 CSV/XLSX 任务都经由 service；不允许 route/worker 导入 SDK；apply 不能越过审核状态。
- [ ] 运行 focused tests 确认当前 LLM suggestion/provider 分支不满足要求而失败。
- [ ] 将 provider-specific options 转换放在 API schema/application options service；CAT service 保持 provider-neutral。
- [ ] 确保取消、任务租约、输出下载和 key 引用保护行为不变。
- [ ] 运行 CAT、translation task、provider service 测试和完整回归。
- [ ] 提交 `feat: connect text providers to CAT workflows`。

### Task 8: 文档、前端契约和真实 provider 验收

**Files:**
- Modify: `docs/api.md`
- Modify: `README.md`
- Modify: `docs/database.md`
- Modify: `env/.env.app`
- Modify: API contract canonical copy and synchronized frontend copy via repository script
- Test: `tests/test_ai_provider_catalog_api.py`
- Test: `tests/test_openapi_contract.py`
- Create: `docs/superpowers/provider-smoke-tests.md`

**Interfaces:**
- `GET /api/v1/ai/providers` 文档化 provider、model、capabilities 和 disabled behavior。
- 翻译任务和 CAT API 文档化 `provider_options`、错误码和多模态明确不支持。

- [ ] 写文档一致性测试：所有 provider 状态、环境变量、接口 description 和 OpenAPI schema 一致。
- [ ] 运行文档检查确认旧的“尚未实现”或错误 provider 列表被发现。
- [ ] 更新中文 API、README、数据库和部署文档，明确 SQLite/mock 与 PostgreSQL/Redis/Celery/真实 API 证据边界。
- [ ] 编写可脱敏的 smoke test 流程：读取已配置 provider、执行一条短文本、检查 usage、删除/轮换测试 key；禁止把 key 写入日志。
- [ ] 运行 `uv run pytest -q`、`uv run python -m compileall -q app migrations`、OpenAPI 检查和 `git diff --check`。
- [ ] 提交 `docs: document complete text provider support`。

## Completion Criteria

1. 每个已启用 provider 都能通过 catalog/registry 解析并严格校验模型和 API Key provider。
2. 所有已支持 provider 都只进行文本输入输出，`supports_multimodal=false`。
3. compatible provider 和 native provider 均能将成功、usage、错误、延迟和 request id 映射到统一 contract。
4. CAT Workbench、Workflow 和 provider adapter 之间没有厂商 SDK 泄漏。
5. 每个实际 provider attempt 都有 usage 明细，secret/prompt/completion 不会持久化或出现在日志中。
6. provider 专属文本 options 有 typed validation，未支持字段拒绝而非静默丢弃。
7. focused tests、完整测试、OpenAPI/docs 检查和真实 smoke test 分开记录。
