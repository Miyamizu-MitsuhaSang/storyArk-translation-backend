# AI Provider 翻译接入设计

## 目标

在现有项目 CAT 架构中接入可替换的 AI 翻译能力：

1. `project/cat/workbench` 负责当前片段的即时 AI 翻译和建议。
2. `project/cat/workflow` 负责 `xlsx`/`csv` 表格的批量翻译任务、状态和人工复核衔接。
3. 上层只传入 `model_type`，由受控 registry 自动选择对应 SDK 或调用函数。
4. 所有 provider 调用统一走项目 API key binding、用量记录、错误归一化和安全审计边界。

## 范围

### 包含

- CAT 单片段 AI 翻译候选和可选草稿写入。
- `xlsx` 和 `csv` 表格批量翻译。
- 指定源语言列、目标语言和目标列映射。
- provider adapter 的统一协议、registry 和懒加载 SDK。
- 项目 API key binding 解析、临时解密和 provider 匹配校验。
- Celery/`BackgroundJob` 批量任务、重试、取消和失败状态。
- `AIUsageRecord` 的调用明细写入。
- Workbench、Workflow、provider registry 和表格读写的测试。

### 不包含

- 新建独立 AI Gateway 服务。
- 允许客户端提交任意 Python 模块、函数路径或 SDK 配置。
- AI 结果自动进入 `in_review`、`approved` 或 `confirmed`。
- 在数据库保存完整 prompt、completion、文件原文或 API secret。
- 一次性实现所有 provider；未注册的 `model_type` 必须明确返回不支持错误。

## 现有边界

- 用户级 AI 凭据由 `app/application/auth/api_key/` 管理，持久化前使用 AES-256-GCM 加密。
- 项目级 API key 由 `app/application/project/api_key/` 管理，只保存 binding，不接收或返回 secret。
- `CatWorkbenchService` 已处理 TM、术语库和世界观建议；`llm` 当前只返回 `LLM_PROVIDER_NOT_IMPLEMENTED`。
- `CatWorkflowService` 已处理片段提交审核、批准、退回、确认和批量工作流动作。
- `Document`/`DocumentSegment` 是 Workbench 读取、编辑、QA 和写入 TM 的现有载体。
- `AIUsageRecord` 是 provider 用量统计的事实来源。

## 总体架构

```text
project/cat/workbench routes
  -> CatWorkbenchService
      -> AiTranslationService
          -> ModelInvokerRegistry
              -> ModelInvoker (OpenAI/Anthropic/Google/...)

project/cat/workflow routes
  -> CatWorkflowService / TranslationTaskService
      -> BackgroundJob / Celery worker
          -> SpreadsheetTranslationService
              -> AiTranslationService
                  -> ModelInvokerRegistry
```

依赖方向保持：

```text
api -> application -> domain
                         ^
application -> repositories / infrastructure
```

`app/domain/ai_translation/` 不依赖 FastAPI、Tortoise、Celery、HTTP 客户端或厂商 SDK。具体 SDK 和表格库只出现在 `app/infrastructure/`。

## 上层统一接口

### 领域请求和结果

```python
class TranslationRequest:
    text: str
    source_language: str
    target_language: str
    model_type: str
    model: str
    context: TranslationContext
    temperature: float | None
    max_tokens: int | None
    request_id: str


class TranslationResult:
    text: str
    provider: str
    model_type: str
    model: str
    provider_request_id: str | None
    usage: UsageSnapshot
    latency_ms: int
    finish_reason: str | None
    warnings: list[str]
```

`TranslationContext` 只允许受控结构化内容，例如前后文、术语命中、世界观条目和风格设置；不得包含 API key、token 或未脱敏异常。

### Invoker 协议

```python
class ModelInvoker(Protocol):
    provider: str

    async def translate(
        self,
        request: TranslationRequest,
        *,
        api_key: str,
    ) -> TranslationResult:
        ...
```

`AiTranslationService.translate(request, credential_binding)` 负责：

1. 校验 `model_type`、语言和文本长度。
2. 通过 registry 解析 invoker。
3. 校验 invoker.provider 与项目 binding 的 provider 一致。
4. 受限地解密用户凭据，并只在调用期间传给 invoker。
5. 对可重试错误执行有上限的指数退避。
6. 将成功、失败或超时统一写入一条 `AIUsageRecord`。
7. 清理错误信息和日志中的 secret、prompt、completion。

## `model_type` Registry

### 注册方式

`model_type` 是服务端受控的稳定 key，不是任意函数路径。初始 registry 结构如下：

```python
MODEL_INVOKERS = {
    "openai.chat": OpenAIChatInvoker,
    "anthropic.messages": AnthropicMessagesInvoker,
    "google.generate_content": GoogleGenerateContentInvoker,
    "custom.openai_compatible": OpenAICompatibleInvoker,
}
```

实际部署只启用已经安装并配置的 adapter；没有实现的类型不得伪造成功结果。

### 解析规则

- 未知 `model_type`：返回 `MODEL_TYPE_UNSUPPORTED`。
- adapter 未安装：返回 `PROVIDER_SDK_UNAVAILABLE`。
- model type 与项目 key provider 不一致：返回 `PROVIDER_KEY_MISMATCH`。
- provider 返回鉴权失败：返回 `PROVIDER_AUTH_FAILED`，不暴露远端响应原文。
- 429、超时和 5xx：按 adapter 能力标记可重试，超过上限后返回稳定错误。
- 4xx 参数错误、内容策略拒绝和响应解析错误：不重试，返回对应稳定错误码。

不得通过 `importlib` 或用户输入动态执行函数。新增 provider 只需新增 invoker、注册一条 `model_type` 映射并补齐 adapter 测试。

## Workbench 接入

### 现有建议接口扩展

保留：

```text
POST /api/v1/projects/{project_id}/segments/{segment_id}/suggestions
```

当请求的 `providers` 包含 `llm` 时：

- `CatWorkbenchService` 调用 `AiTranslationService`。
- 结果写入 `SegmentSuggestion`，`source="llm"`。
- 记录 provider、model、model type、延迟、警告和受控证据引用。
- provider 失败只增加稳定 warning，不吞掉 TM、术语库和世界观结果。

### 即时翻译动作

新增：

```text
POST /api/v1/projects/{project_id}/segments/{segment_id}/ai-translate
```

请求必须包含：

- `model_type` 和 `model`。
- `version`。
- 当前片段 `lock_token`。
- `apply`，默认 `false`。

`apply=false` 只返回候选译文；`apply=true` 才更新 `DocumentSegment.target_text`，并执行：

```text
status = translated
workflow_state = draft
version += 1
```

AI 翻译不得绕过 QA、提交审核、批准或确认流程。

## Workflow 接入

### 批量任务接口

保留并实现：

```text
GET  /api/v1/projects/{project_id}/translation-tasks
POST /api/v1/projects/{project_id}/translation-tasks
GET  /api/v1/projects/{project_id}/translation-tasks/{task_id}
```

路由归入 `app/api/modules/project/cat/workflow/`，服务由 `TranslationTaskService` 实现，并由 `CatWorkflowService` 统一复用项目成员、审核和状态规则。

批量请求至少包含：

```json
{
  "file_id": "file-1",
  "model_type": "openai.chat",
  "model": "gpt-4o-mini",
  "source_column": "source_zh",
  "target_columns": [
    {"language": "en", "column": "target_en"},
    {"language": "ko", "column": "target_ko"}
  ],
  "project_api_key_id": "binding-1",
  "overwrite": false
}
```

任务创建时必须验证：文件属于当前项目、格式为 `xlsx` 或 `csv`、源列存在、目标列语言不重复、目标语言不等于源语言、项目 binding active 且 provider 匹配。

### 任务状态

```text
queued -> translating -> review -> completed
                  \-> failed
queued/translating -> cancelled
```

- `queued`：任务已创建，等待 worker。
- `translating`：worker 正在读取表格和调用 provider。
- `review`：所有可处理单元格已完成，结果已写入目标列和项目片段草稿，等待人工复核。
- `completed`：复核/确认流程完成，输出文件可作为最终版本使用。
- `failed`：达到重试上限或出现不可重试错误。
- `cancelled`：用户取消后不再领取新批次；正在进行的单次 provider 调用完成后停止后续批次。

客户端不能通过 PATCH 任意伪造任务进度或跳过工作流状态。

## 表格处理边界

### CSV

- 使用标准库 `csv` 读取和写回。
- 只修改请求指定的目标列。
- 保留表头、列顺序、未涉及列和未翻译行。
- CSV 不承诺 Excel 样式，因为格式本身不携带单元格样式。

### XLSX

- 使用 `openpyxl` 读取和写回工作簿。
- 默认处理所有工作表；请求可限制 `sheet_names`。
- 只读取指定源列中的普通字符串/数字单元格；空单元格和公式单元格保持不变。
- 目标列不存在时创建列；目标单元格复制源单元格的样式、数字格式、对齐和保护属性。
- `overwrite=false` 时不覆盖已有目标译文；`overwrite=true` 才允许覆盖。
- 保留其他工作表、非翻译列、合并单元格和工作簿元数据；不保证第三方扩展宏的完全保留。

每个表格单元格都映射到项目 `DocumentSegment`，并在受控 `context` 中保存工作表名、源单元格地址和目标列地址，供 Workbench 复核和重新导出。`context` 不保存 prompt、completion 或 secret。

### 批次和并发

- worker 按目标语言和 provider 支持的批大小分组。
- 批次失败只重试当前批次，不重复提交已成功且已记录 usage 的批次。
- 每批次使用稳定的幂等 request ID。
- provider 并发和速率限制由 adapter capability 与应用配置共同约束。

## 错误与安全

- 路由只负责 HTTP 参数、鉴权、状态码和响应模型；不得调用 SDK。
- 只有 application service 可以解析项目 binding 并调用 credential decrypt。
- API secret 只以明文存在于受限调用栈；不得进入 `BackgroundJob.result`、审计、日志、错误、导出或响应。
- `AIUsageRecord` 只保存 provider、model、tokens、cost、状态、请求 ID、耗时和错误码，不保存输入输出原文。
- provider 返回内容超出长度、缺少译文字段或不符合响应 schema 时返回 `PROVIDER_RESPONSE_INVALID`。
- 单片段和批量任务都必须在失败时保留可查询的稳定错误码；对外错误信息不能包含远端响应原文。

## 文件和模块计划边界

计划实施时优先新增以下独立模块：

```text
app/domain/ai_translation/
app/application/ai_translation/
app/infrastructure/ai_provider/
app/infrastructure/spreadsheet/
app/application/project/cat/workflow/translation_task/
app/api/modules/project/cat/workflow/translation_task_routes.py
app/tasks/translation_tasks.py
```

需要修改的既有模块：

```text
app/application/project/cat/schemas.py
app/application/project/cat/workbench/service.py
app/application/project/cat/workflow/service.py
app/api/modules/project/cat/workbench/routes.py
app/api/modules/project/cat/workflow/routes.py
app/api/modules/project/cat/dependencies.py
app/models/document.py
app/models/ai_usage.py
app/application/auth/api_key/service.py
app/application/project/api_key/service.py
```

具体文件以实施阶段的现状检查为准；不得为了适配模板创建无职责的转发文件。

## 测试策略

### Domain/application

- registry 根据 `model_type` 选择正确 invoker。
- 未知类型、provider mismatch、SDK 缺失和错误分类符合稳定错误码。
- `AiTranslationService` 成功、超时、429、5xx、鉴权失败和响应解析失败均写入正确 usage 状态。
- secret、prompt、completion 不出现在异常、日志和 job result。

### Workbench

- `llm` 建议和 `ai-translate` 路由已注册。
- 无锁、版本冲突、非项目 binding 和 inactive key 被拒绝。
- `apply=false` 不改 segment；`apply=true` 只写入 draft/translated。
- provider 失败不会阻断 TM/术语库/世界观建议。

### Workflow/batch

- xlsx 多工作表和 csv 指定列映射正确。
- 非翻译列、空单元格、公式单元格和已有目标译文按契约保留。
- provider 批次重试不重复写入成功结果或 usage。
- 任务状态只能按允许的状态转换推进，不能直接跳过 review。
- 输出文件可重新导入，片段能在 Workbench 中按 cell context 定位。

### 集成边界

使用 fake invoker 验证完整调用链；真实 provider 只在存在受控测试凭据和网络条件时执行单独 smoke test。SQLite、本地 Celery 配置或 OpenAPI 注册成功不能证明 PostgreSQL、Redis、Celery 或真实 provider 已部署可用。

## 分阶段实施顺序

1. 建立 domain contracts、registry、fake invoker 和 `AiTranslationService`。
2. 接入 Workbench `llm` 建议和 `ai-translate` 动作。
3. 增加 `xlsx`/`csv` parser/writer 与表格映射模型。
4. 在 Workflow 中实现批量任务、worker、重试、输出文件和 segment 草稿写入。
5. 接入首个真实 provider adapter，并补充 usage/错误/限流测试。
6. 更新 `api-contract/docs/api.md`、backend `docs/api.md` 和 README，运行文档同步与完整验证。
