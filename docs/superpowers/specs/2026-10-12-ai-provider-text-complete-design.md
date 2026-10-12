# AI Provider 文本翻译完整接入设计

## 1. 目标

在现有 FastAPI CAT 后端中建立可扩展的多厂商文本翻译层，统一接入协议、权限、密钥、错误、重试、用量统计和人工复核流程，同时保留各厂商的文本能力差异。

本设计只覆盖文本输入和文本输出。图片、音频、视频、视觉理解、语音识别、语音合成和其他多模态 content parts 不在本期范围内。

## 2. 当前基线

当前后端已经具备：

- `TranslationRequest`、`TranslationResult`、`UsageSnapshot` 领域 contract；
- `ModelInvoker` 协议和服务端 allowlist registry；
- `openai.chat` adapter；
- 基于 OpenAI-compatible 协议的 DeepSeek、Qwen adapter；
- 用户级 API key 的 AES-256-GCM 加密和脱敏返回；
- `AiTranslationService` 的项目成员校验、provider 匹配和 AI 用量写入；
- CAT Workbench 单片段和 Workflow 表格翻译任务的调用边界；
- `AIUsageRecord` 作为调用用量事实来源。

当前限制：

- registry 仍以简单 `model_type -> registration` 为主，缺少独立 provider catalog；
- compatible adapter 只覆盖通用 Chat Completions 字段；
- reasoning、cached token、厂商专属文本选项尚未统一；
- Anthropic 和 Google 原生协议尚未接入；
- provider 列表和模型能力没有正式 API；
- 真实 provider smoke test、PostgreSQL/Redis/Celery 生产验收尚未完成。

## 3. 范围边界

### 3.1 包含

- OpenAI-compatible 文本翻译：OpenAI、DeepSeek、Qwen、Kimi、Doubao、Zhipu、MiniMax、Groq、Mistral；
- 原生文本协议：Anthropic Messages、Google Gemini/Generative Language；
- 单片段 CAT 翻译和 CSV/XLSX 批量翻译；
- 多模型选择、模型 allowlist 和能力声明；
- system prompt、上下文、术语、世界观和风格等结构化文本上下文；
- temperature、max tokens、stop、reasoning/thinking 等已验证的文本参数；
- provider 超时、限流、认证、模型不可用、内容安全拒绝和服务错误的稳定错误码；
- provider 调用级 usage、成本、延迟、请求 ID 和审计；
- mock HTTP 测试、契约测试、真实 API smoke test 和部署验收文档。

### 3.2 不包含

- 任意图片、音频、视频或视觉输入输出；
- 任意 provider 的通用 agent、联网搜索、图片生成或文件分析产品；
- 允许客户端传入任意 endpoint、SDK 类名、Python 模块路径或原始厂商 payload；
- 在数据库保存完整 prompt、completion、原始 provider 响应或 API secret；
- 自动把 AI 译文标记为 `in_review`、`approved` 或 `confirmed`。

## 4. 总体架构

```text
CAT Workbench / Workflow API
        |
        v
AiTranslationService
        |
        +--> ProviderCatalog / ModelInvokerRegistry
        |          |
        |          +--> OpenAIChatInvoker
        |          +--> OpenAICompatibleInvoker
        |          +--> AnthropicMessagesInvoker
        |          +--> GoogleGenerativeInvoker
        |
        +--> ApiKeyService -> encrypted user credential
        +--> AIUsageRepository -> PostgreSQL fact records
        +--> RetryPolicy / ErrorMapper
```

依赖方向保持：

```text
api -> application -> domain
application -> infrastructure / repositories
domain -> no FastAPI, Tortoise, Celery or vendor SDK
```

厂商 SDK、HTTP 客户端和 provider response parser 只能位于 `app/infrastructure/ai_provider`。CAT、任务 worker 和 analytics 不得导入厂商 SDK或按 provider 写条件分支。

## 5. 统一文本 contract

### 5.1 请求

```python
TranslationRequest(
    text: str,
    source_language: str,
    target_language: str,
    model_type: str,
    model: str,
    context: TranslationContext,
    options: ProviderTextOptions,
    request_id: UUID | None,
)
```

`TranslationContext` 只允许受控结构化文本字段：前后文、术语命中、世界观条目、风格规则和任务标签。构造时拒绝 `api_key`、`secret`、`token`、`password`、`credential` 等字段。

`ProviderTextOptions` 是不可变的已校验对象。基础字段包括 `temperature`、`max_tokens` 和 `stop`；厂商差异通过具有明确类型的 provider options 扩展，不接受任意字典或原始 JSON。

### 5.2 结果

```python
TranslationResult(
    text: str,
    provider: str,
    model_type: str,
    model: str,
    provider_request_id: str | None,
    usage: UsageSnapshot,
    latency_ms: int | None,
    finish_reason: str | None,
    warnings: tuple[str, ...],
)
```

`UsageSnapshot` 必须支持：

- `input_tokens`；
- `output_tokens`；
- `cached_input_tokens`；
- `reasoning_tokens`；
- `total_tokens`。

provider 未提供某字段时填 `0`，不得凭空估算为 provider 计费值。所有 token 字段不得为负数。

### 5.3 能力

每个 model registration 必须声明：

- `supports_system_message`；
- `supports_temperature`；
- `supports_max_tokens`；
- `supports_stop`；
- `supports_reasoning`；
- `supports_cached_tokens`；
- `supports_structured_text`；
- `supports_multimodal`，本设计接入的所有模型固定为 `false`。

不支持的参数必须在调用前返回 `MODEL_OPTION_UNSUPPORTED`，不能静默丢弃。

## 6. Provider Catalog 和 Registry

`ProviderCatalog` 是服务端控制的静态/配置化目录。每个条目至少包含：

```text
model_type
provider
adapter_kind
enabled
endpoint_name
model_allowlist
capabilities
credential_provider
```

endpoint 只能从 `.env.app` 或受控部署配置读取。请求体不允许覆盖 endpoint、HTTP headers、TLS 设置或 SDK 参数。

registry 负责：

1. 解析受控 `model_type`；
2. 校验 provider 是否启用；
3. 校验模型是否在 allowlist；
4. 返回 adapter 和能力声明；
5. 校验 credential provider 与 registration provider 一致；
6. 返回可供前端选择的脱敏 catalog。

未知 `model_type`、停用 provider 和不支持模型分别使用稳定错误码：

```text
MODEL_TYPE_UNSUPPORTED
PROVIDER_NOT_CONFIGURED
MODEL_UNSUPPORTED
```

## 7. Adapter 分层

### 7.1 OpenAI-compatible adapter

以下 provider 共用协议基础，但每个 registration 独立配置 provider、endpoint、模型列表、错误映射和 usage 映射：

```text
openai.chat
deepseek.chat
qwen.chat
kimi.chat
doubao.chat
zhipu.chat
minimax.chat
groq.chat
mistral.chat
```

通用调用使用文本 `chat.completions.create` 语义，但 adapter 不应假设所有厂商的扩展字段都一致。厂商专属字段通过 options mapper 显式映射。

### 7.2 原生 adapter

`anthropic.messages` 使用 Anthropic Messages 原生消息结构；`google.gemini` 使用 Google Generative Language 原生内容结构。二者都只发送文本 content，并映射到统一结果和 usage contract。

## 8. 厂商文本能力

厂商专属能力必须保持在 adapter/options 层：

- DeepSeek：reasoning 模型和 reasoning token；
- Qwen：thinking 开关、thinking token 和文本 generation 参数；
- Kimi：长上下文文本参数；
- Doubao/Zhipu/MiniMax：其兼容接口的 stop、temperature、max token 和 usage 差异；
- Anthropic：extended thinking、max tokens、stop sequences；
- Google：generation config、safety settings 和 finish reason。

只有经过 contract 测试确认的参数才能暴露给 API。不能因某个 provider 接受任意字段，就把该字段传给其他 provider。

## 9. Application 调用和可靠性

`AiTranslationService` 负责：

1. 项目成员和 API key 所有权校验；
2. registry/model/options 校验；
3. 受限解密 secret；
4. 调用 adapter；
5. 对可重试错误执行有限指数退避；
6. 每个实际 provider attempt 写一条不可变 usage 明细；
7. 返回脱敏的稳定错误；
8. 确保 AI 结果只进入草稿/已翻译状态。

只对 timeout、明确限流和明确可重试的 5xx 重试；认证失败、模型不支持、参数错误、内容安全拒绝不重试。默认最多 3 次实际 attempt，退避时间由应用配置控制。

## 10. CAT 与前端职责

后端：

- Workbench 负责单 segment 翻译和可选草稿应用；
- Workflow 负责 CSV/XLSX 批量翻译和任务状态；
- 业务层不导入厂商 SDK；
- 结果不得自动进入审核状态；
- provider usage 统一写入 `AIUsageRecord`。

前端：

- 通过 provider catalog 选择可用的 `model_type` 和 `model`；
- 只渲染能力声明允许的文本参数；
- 不显示或保存 API secret；
- 展示稳定错误码、provider、model 和用量；
- 本期不显示任何多模态控件。

建议新增：

```text
GET /api/v1/ai/providers
```

响应只包含 provider、model_type、模型标识和 capabilities，不包含实际 endpoint、密钥或内部异常。

## 11. 数据和安全

- API key 继续通过用户级 auth API 管理，并以 AES-256-GCM 加密保存；
- prompt、completion、原始文件内容和 secret 不进入数据库、日志、任务结果或审计事件；
- `AIUsageRecord` 保存 provider、model、request id、token、成本、状态、延迟和稳定错误码；
- provider request id 与 provider 一起用于幂等去重，但不能伪造为应用 request id；
- endpoint、模型白名单和启用开关属于服务端配置；
- 不允许 SSRF、任意 header 注入或动态 SDK 导入。

## 12. 分期交付

1. 完善 contract、能力和稳定错误；
2. 建立 ProviderCatalog、模型能力查询和配置校验；
3. 完成 OpenAI-compatible provider 全部文本接入；
4. 完成 Anthropic/Google 原生文本 adapter；
5. 完成厂商专属文本 options、reasoning 和 usage；
6. 接入 Workbench、Workflow、重试、usage 和审计；
7. 完成 API 文档、真实 smoke test 和部署验收。

每一期都必须先写失败测试，再实现最小代码，并保持现有完整测试通过。

## 13. 完成标准

某个 provider 只有同时满足以下条件才标记为“已支持”：

1. registry 可解析且启用开关有效；
2. 模型 allowlist 和能力校验有效；
3. API key provider 严格匹配；
4. 文本翻译成功路径通过；
5. token、成本、request id 和延迟正确记录；
6. timeout、限流、认证、模型错误和内容安全错误有稳定映射；
7. 重试边界和幂等 usage 通过测试；
8. secret、prompt、completion 和原始响应不会泄露；
9. adapter、application、API 和任务 worker 测试通过；
10. 至少完成 mock HTTP 测试和一次真实 API smoke test；
11. 环境变量、API 文档和运行边界同步；
12. 明确声明 `supports_multimodal=false`。
