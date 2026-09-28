# Translation Platform API

通用 CAT/AI 翻译平台 API 设计草案。本文档描述第一版业务 API 契约，作为 FastAPI 路由、Pydantic Schema 和前端 API client 的共同依据。

当前仓库只实现了健康检查和基础 RAG 验证接口；本文档中的认证、项目、文档、segment、术语、TM、审核和导出接口属于后续实现范围。设计先以通用游戏本地化 CAT 平台为目标，后续可以根据实际业务删减字段。

## 文档源与同步

`api-contract/docs/api.md` 是 API 文档的唯一源文件。仓库内的以下文件是可分别提交到前端、后端 Git 仓库的同步副本：

```text
docs/api.md
src/translation_backend/docs/api.md
src/translation_frontend/docs/api.md
```

修改 API 文档后，在仓库根目录执行：

```bash
./scripts/sync-api-docs.sh
```

不要直接编辑三个副本。未来将前端和后端拆成独立仓库时，可以把各自的 `docs/api.md` 和同步后的提交分别上传，不依赖跨仓库软链接。

## 1. 基本约定

### 1.1 Base URL

```text
/api/v1
```

开发环境完整地址为 `http://127.0.0.1:8000/api/v1`。

所有业务接口使用 JSON，文件上传使用 `multipart/form-data`，文件导出使用二进制响应或异步任务。

### 1.2 Authentication

登录支持用户名或邮箱加密码：

```http
Authorization: Bearer <access_token>
```

- `access_token`：短期令牌，建议有效期 15 分钟；
- `refresh_token`：长期令牌，建议有效期 30 天，并采用轮换机制；
- 密码只保存为 Argon2id 哈希；
- 除登录、刷新、健康检查外，所有接口默认需要认证；
- 所有业务数据必须通过 `project_id` 做项目级隔离。

### 1.3 Common headers

```http
Content-Type: application/json
X-Request-ID: <client-generated-uuid>
Idempotency-Key: <uuid-for-retryable-write>
```

服务端应该在响应中原样返回 `X-Request-ID`。创建任务、导入文件、导出文件等可重试写操作应支持 `Idempotency-Key`。

### 1.4 Pagination and filtering

列表接口统一支持：

```text
page_size: 1..100，默认 20
cursor: 不透明分页游标
q: 全文搜索关键词
sort: 排序字段，默认 created_at 或 updated_at
```

统一响应格式：

```json
{
  "items": [],
  "next_cursor": "opaque-cursor-or-null",
  "total": 0
}
```

### 1.5 Error response

错误响应使用统一结构：

```json
{
  "error": {
    "code": "SEGMENT_LOCKED",
    "message": "该 segment 已被其他用户锁定",
    "details": {
      "locked_by": "user-123",
      "locked_until": "2026-09-20T12:30:00Z"
    },
    "request_id": "req-123"
  }
}
```

常见状态码：

| 状态码 | 用途 |
| --- | --- |
| `400` | 请求格式或业务参数错误 |
| `401` | 未登录、令牌无效或已过期 |
| `403` | 没有项目或资源权限 |
| `404` | 资源不存在，或当前用户不可见 |
| `409` | 状态冲突、版本冲突、segment 已锁定 |
| `422` | Pydantic 字段校验失败 |
| `429` | 登录、模型调用或搜索频率限制 |
| `500` | 未预期的服务端错误 |
| `503` | 外部模型、队列或存储暂时不可用 |

## 2. 核心领域模型

### 2.1 User

```json
{
  "id": "user-123",
  "username": "translator01",
  "email": "translator@example.com",
  "display_name": "张译员",
  "status": "active",
  "roles": ["translator"],
  "created_at": "2026-09-20T09:00:00Z"
}
```

角色建议：

| 角色 | 主要权限 |
| --- | --- |
| `owner` | 项目全部权限、成员和配置管理 |
| `manager` | 项目资源、任务、术语、TM 和工作流管理 |
| `translator` | 获取上下文、编辑和提交自己的 segment |
| `reviewer` | 审核、退回、批准 segment，执行 QA |
| `viewer` | 只读访问项目内容 |

### 2.2 Project and language pair

项目是所有资源的租户边界。一个项目可以配置多个源语言和目标语言对：

```json
{
  "id": "project-123",
  "name": "Project Aurora",
  "description": "Aurora 游戏本地化项目",
  "source_languages": ["zh-CN"],
  "target_languages": ["en-US", "ja-JP"],
  "default_language_pair": {
    "source": "zh-CN",
    "target": "en-US"
  },
  "status": "active"
}
```

### 2.3 Segment

segment 是 CAT 编辑器的最小工作单元：

```json
{
  "id": "seg-123",
  "document_id": "doc-123",
  "segment_no": 42,
  "source": "欢迎来到晨曦大陆。",
  "target": "Welcome to the Dawn Continent.",
  "source_language": "zh-CN",
  "target_language": "en-US",
  "status": "in_translation",
  "workflow_state": "draft",
  "version": 7,
  "locked_by": "user-123",
  "locked_until": "2026-09-20T12:30:00Z",
  "qa_summary": {
    "error": 0,
    "warning": 1,
    "info": 0
  },
  "updated_at": "2026-09-20T12:20:00Z"
}
```

segment 状态：

```text
untranslated -> in_translation -> translated -> in_review -> approved
                                      \-> rejected -> in_translation
approved -> confirmed
```

`draft`、`translated`、`approved` 等状态变化必须产生审计记录。`version` 用于乐观锁，更新时客户端应发送 `If-Match` 或 `version`。

## 3. Authentication API

### POST `/auth/login`

使用用户名或邮箱登录。

Request:

```json
{
  "login": "translator01",
  "password": "password",
  "remember_me": true
}
```

Response `200`:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "user-123",
    "username": "translator01",
    "email": "translator@example.com",
    "display_name": "张译员"
  }
}
```

失败返回 `401 INVALID_CREDENTIALS`。不要区分“用户名不存在”和“密码错误”。

### POST `/auth/refresh`

Request:

```json
{ "refresh_token": "eyJ..." }
```

返回新的 access token 和轮换后的 refresh token。旧 refresh token 立即失效。

### POST `/auth/logout`

撤销当前 refresh token。返回 `204 No Content`。

### GET `/auth/me`

返回当前用户和可访问项目摘要。

### PATCH `/auth/me/password`

Request:

```json
{
  "current_password": "old-password",
  "new_password": "new-password"
}
```

成功返回 `204`，并撤销当前用户的其他 refresh token。

### GET/POST `/auth/me/api-keys`

当前登录用户管理自己拥有的 AI provider API key。该接口属于认证/用户域，不绑定具体项目；同一用户可以为同一个 provider 保存多把 key。

GET 返回脱敏元数据，不包含 secret 原文：

```json
{
  "items": [
    {
      "id": "user-key-123",
      "provider": "openai",
      "label": "工作账号",
      "masked_secret": "sk-proj-••••••••1234",
      "last_four": "1234",
      "status": "active",
      "created_at": "2026-09-24T03:00:00Z",
      "last_used_at": "2026-09-24T03:10:00Z"
    }
  ],
  "next_cursor": null,
  "total": 1
}
```

POST 只接受一次性 write-only secret：

```json
{
  "provider": "openai",
  "label": "工作账号",
  "secret": "sk-proj-example"
}
```

成功返回 `201`，只返回 `{id,provider,label,masked_secret,last_four,status,created_at}`，绝不返回 `secret`。支持的 provider 包括 `openai`（ChatGPT）、`anthropic`（Claude）、`google`、`qwen`、`deepseek`、`kimi`、`doubao`、`zhipu`、`minimax`、`mistral`、`groq` 和 `custom`。响应、日志、审计事件、错误信息和追踪数据均不得包含 secret。

### GET/PATCH/DELETE `/auth/me/api-keys/{key_id}`

GET 返回单个 key 的脱敏元数据。PATCH 只允许修改 `{label,status}`；如需轮换 secret，必须重新 POST 创建一把 key，再停用旧 key。DELETE 永久删除该用户 key；如果该 key 仍绑定项目，返回 `409 API_KEY_IN_USE`，必须先解除所有项目绑定。用户只能访问自己的 key，不存在时统一返回 `404`。

## 4. Project API

### GET `/projects`

返回当前用户可访问的项目列表，支持 `status`、`q` 和分页。

### POST `/projects`

创建项目。创建者自动成为 `owner`。

```json
{
  "name": "Project Aurora",
  "description": "游戏本地化项目",
  "source_languages": ["zh-CN"],
  "target_languages": ["en-US", "ja-JP"]
}
```

### GET `/projects/{project_id}`

返回项目配置、成员统计和语言对。

### PATCH `/projects/{project_id}`

更新名称、描述、状态和默认语言对。需要 `owner` 或 `manager`。

### GET `/projects/{project_id}/members`

获取项目成员，支持按角色和关键词筛选。

### POST `/projects/{project_id}/members`

```json
{
  "user_id": "user-456",
  "role": "translator"
}
```

### PATCH `/projects/{project_id}/members/{user_id}`

修改项目角色。不能通过此接口删除最后一个 `owner`。

### DELETE `/projects/{project_id}/members/{user_id}`

移除成员。需要 `owner` 或 `manager`。

### GET `/projects/{project_id}/language-pairs`

获取项目的源语言、目标语言组合及其启用状态。

### POST `/projects/{project_id}/language-pairs`

```json
{
  "source_language": "zh-CN",
  "target_language": "en-US",
  "is_default": true
}
```

## 5. 世界观与项目上下文 API

世界观是游戏本地化中区别于普通翻译平台的核心上下文。它包含世界设定、角色、阵营、地点、物品、技能、任务、叙事规则和风格要求。世界观条目会参与翻译建议和 QA，但不直接修改原始 segment。

### GET `/projects/{project_id}/worldview`

返回当前项目的世界观版本、摘要和启用状态。

### PATCH `/projects/{project_id}/worldview`

更新项目级风格指南和全局规则：

```json
{
  "name": "Aurora World Bible",
  "style_guide": "角色名保持官方大小写；UI 文案简洁；不要翻译占位符。",
  "default_tone": "fantasy-adventure",
  "version_note": "新增阵营命名规范",
  "status": "active"
}
```

### GET `/projects/{project_id}/worldview/entries`

按 `type`、`q`、`status` 查询世界观条目。条目类型建议：

```text
character, faction, location, item, skill, quest, creature,
system, lore, rule, style_guide
```

### POST `/projects/{project_id}/worldview/entries`

```json
{
  "type": "character",
  "name": "艾琳",
  "aliases": ["曙光骑士", "Eileen"],
  "description": "晨曦骑士团的团长，谨慎而坚定。",
  "attributes": {
    "gender": "female",
    "register": "formal"
  },
  "language_variants": {
    "en-US": "Eileen",
    "ja-JP": "エイリーン"
  },
  "tags": ["main-character"]
}
```

### GET `/projects/{project_id}/worldview/entries/{entry_id}`

获取单条世界观条目及其版本历史摘要。

### PATCH `/projects/{project_id}/worldview/entries/{entry_id}`

更新条目。更新应生成新版本，不覆盖历史版本。

### DELETE `/projects/{project_id}/worldview/entries/{entry_id}`

软删除条目，已被 segment 或术语引用的条目不得物理删除。

### GET `/projects/{project_id}/context`

按 segment 或关键词聚合返回翻译上下文，供 CAT 工作台一次请求获取：

```text
GET /projects/project-123/context?segment_id=seg-123&include=worldview,terms,tm,neighbors
```

返回相邻 segment、相关世界观条目、术语命中、TM 匹配和项目风格规则。

## 6. Terminology API

### GET `/projects/{project_id}/terminology-bases`

获取项目术语库列表。术语库可以按项目、版本或领域拆分，例如角色名库、UI 术语库、法律术语库。

### POST `/projects/{project_id}/terminology-bases`

```json
{
  "name": "Aurora Official Terms",
  "description": "官方角色、地名和 UI 术语",
  "source_language": "zh-CN",
  "target_languages": ["en-US", "ja-JP"],
  "priority": 100,
  "status": "active"
}
```

### GET `/projects/{project_id}/terminology-bases/{base_id}/terms`

按 `q`、`term_type`、`status`、`language` 和分页查询术语。

### POST `/projects/{project_id}/terminology-bases/{base_id}/terms`

```json
{
  "source_term": "晨曦骑士团",
  "target_terms": {
    "en-US": "Dawn Knights",
    "ja-JP": "ドーンナイツ"
  },
  "term_type": "faction",
  "status": "approved",
  "forbidden_translations": ["Knights of Dawn"],
  "case_sensitive": false,
  "notes": "官方译名，不要添加 the",
  "worldview_entry_id": "entry-faction-001"
}
```

`term_type` 建议值：`character`、`faction`、`location`、`item`、`skill`、`ui`、`general`。

### GET `/projects/{project_id}/terminology-bases/{base_id}/terms/{term_id}`

返回术语的语言变体、状态、来源、版本和审计信息。

### PATCH `/projects/{project_id}/terminology-bases/{base_id}/terms/{term_id}`

更新术语。已批准术语的译文变更需要 `manager` 或 `owner`，并产生术语版本。

### DELETE `/projects/{project_id}/terminology-bases/{base_id}/terms/{term_id}`

软删除或停用术语。

### POST `/projects/{project_id}/terminology/search`

为工作台或 QA 查询术语命中：

```json
{
  "text": "艾琳率领晨曦骑士团进入灰烬港。",
  "source_language": "zh-CN",
  "target_language": "en-US",
  "include_forbidden": true
}
```

响应应标出 `approved`、`forbidden`、`suggested` 和命中位置，便于前端高亮。

## 7. Translation Memory API

### GET `/projects/{project_id}/translation-memories`

获取 TM 库及其语言对、优先级、条目数和索引状态。

### POST `/projects/{project_id}/translation-memories`

创建 TM 库：

```json
{
  "name": "Aurora Main TM",
  "source_language": "zh-CN",
  "target_language": "en-US",
  "priority": 100
}
```

### POST `/projects/{project_id}/tm/search`

检索精确匹配、模糊匹配和语义匹配：

```json
{
  "source_text": "欢迎来到晨曦大陆。",
  "source_language": "zh-CN",
  "target_language": "en-US",
  "top_k": 10,
  "min_score": 0.65,
  "include_rag": true,
  "context": {
    "document_id": "doc-123",
    "segment_id": "seg-123"
  }
}
```

结果应包含 `match_type`、`score`、源文、译文、来源文档、确认人和术语/世界观上下文：

```json
{
  "items": [
    {
      "id": "tm-456",
      "source_text": "欢迎来到晨曦大陆。",
      "target_text": "Welcome to the Dawn Continent.",
      "score": 1.0,
      "match_type": "exact",
      "source": "confirmed_translation",
      "metadata": {"document_id": "doc-old"}
    }
  ],
  "next_cursor": null,
  "total": 1
}
```

### POST `/projects/{project_id}/translation-memories/{tm_id}/entries`

手动导入或创建 TM 条目。已确认的 segment 也通过工作流自动写入 TM。

### POST `/projects/{project_id}/translation-memories/{tm_id}/reindex`

异步重建 TM/RAG 索引，返回 `202` 和 `job_id`。

## 8. Document and import/export API

### GET `/projects/{project_id}/documents`

按语言对、状态、文件名、创建人和时间筛选文档。

### POST `/projects/{project_id}/documents`

使用 `multipart/form-data` 上传 XLIFF、CSV、JSON、PO、TXT 等文件。字段：

```text
file: binary
source_language: zh-CN
target_language: en-US
name: optional-display-name
tm_ids[]: optional
```

返回 `202 Accepted`：

```json
{
  "document": {"id": "doc-123", "status": "uploaded"},
  "job_id": "job-import-123"
}
```

### GET `/projects/{project_id}/documents/{document_id}`

返回文档状态、segment 统计、语言对、版本和导入错误。

### POST `/projects/{project_id}/documents/{document_id}/parse`

重新解析文档，返回异步 `job_id`。如果已有翻译内容，必须要求显式 `preserve_translations` 选项。

### GET `/projects/{project_id}/documents/{document_id}/segments`

工作台主列表接口，支持：

```text
status, workflow_state, assigned_to, q, segment_no_from, segment_no_to,
page_size, cursor, sort
```

### POST `/projects/{project_id}/documents/{document_id}/export`

```json
{
  "format": "xliff",
  "include_untranslated": false,
  "include_review_notes": false
}
```

返回 `202` 和 `job_id`。通过任务接口查询完成状态，完成后返回临时下载 URL。

## 9. CAT translation workbench API

### GET `/projects/{project_id}/segments/{segment_id}`

返回 segment、前后文、当前锁、术语命中和最近修改记录摘要。

### POST `/projects/{project_id}/segments/{segment_id}/lock`

锁定 segment。建议默认锁定 15 分钟，前端在编辑期间通过续租保持锁。

Response `200`：

```json
{
  "segment_id": "seg-123",
  "lock_token": "lock-123",
  "locked_by": "user-123",
  "locked_until": "2026-09-20T12:30:00Z"
}
```

### POST `/projects/{project_id}/segments/{segment_id}/lock/renew`

使用 `lock_token` 续租锁。其他用户锁定时返回 `409 SEGMENT_LOCKED`。

### DELETE `/projects/{project_id}/segments/{segment_id}/lock`

释放当前用户的锁。

### PATCH `/projects/{project_id}/segments/{segment_id}`

保存译文草稿或译者备注：

```json
{
  "target": "Welcome to the Dawn Continent.",
  "translator_note": "大陆名称来自世界观条目",
  "version": 7,
  "lock_token": "lock-123",
  "save_as": "draft"
}
```

版本不一致返回 `409 SEGMENT_VERSION_CONFLICT`，响应中带最新 segment，前端需要让用户选择合并或覆盖。

### POST `/projects/{project_id}/segments/{segment_id}/suggestions`

生成该 segment 的翻译建议。建议来源包括 TM、术语库、世界观、规则引擎、机器翻译和 LLM：

```json
{
  "providers": ["tm", "terminology", "worldview", "rag", "llm"],
  "include_explanation": true,
  "temperature": 0.2,
  "lock_token": "lock-123"
}
```

响应 `200` 或异步 `202`：

```json
{
  "segment_id": "seg-123",
  "suggestions": [
    {
      "id": "suggestion-1",
      "text": "Welcome to the Dawn Continent.",
      "source": "tm",
      "score": 1.0,
      "evidence": [{"type": "tm", "id": "tm-456"}],
      "warnings": []
    },
    {
      "id": "suggestion-2",
      "text": "Welcome to Dawn Continent.",
      "source": "llm",
      "score": 0.78,
      "evidence": [
        {"type": "worldview", "id": "entry-location-001"},
        {"type": "terminology", "id": "term-001"}
      ],
      "warnings": ["STYLE_VARIANT"]
    }
  ]
}
```

模型建议必须保存 provider、model、prompt/context 版本、证据引用和耗时，便于审计和复现。

### POST `/projects/{project_id}/segments/{segment_id}/qa`

执行 QA 检查：

```json
{
  "checks": ["placeholders", "numbers", "tags", "terminology", "length", "style"],
  "save_results": true
}
```

返回问题列表：

```json
{
  "segment_id": "seg-123",
  "summary": {"error": 0, "warning": 1, "info": 0},
  "issues": [
    {
      "id": "qa-1",
      "rule": "terminology",
      "severity": "warning",
      "message": "建议使用官方术语 Dawn Knights",
      "source_span": [0, 0],
      "target_span": [0, 0],
      "can_ignore": true
    }
  ]
}
```

## 10. Translation workflow actions

### POST `/projects/{project_id}/segments/{segment_id}/submit-review`

将当前译文从 `translated` 或 `draft` 提交到 `in_review`。要求：持有锁、译文非空、必需 QA 错误已处理或明确豁免。

```json
{
  "version": 8,
  "lock_token": "lock-123",
  "comment": "已完成初译"
}
```

### POST `/projects/{project_id}/segments/{segment_id}/approve`

审核通过，状态变为 `approved`。需要 `reviewer`、`manager` 或 `owner`。

```json
{
  "version": 8,
  "comment": "术语和上下文正确"
}
```

### POST `/projects/{project_id}/segments/{segment_id}/reject`

审核退回，状态变为 `rejected`，必须填写退回原因：

```json
{
  "version": 8,
  "reason": "角色称谓不符合世界观设定",
  "issue_ids": ["qa-1"]
}
```

### POST `/projects/{project_id}/segments/{segment_id}/confirm`

将已批准译文确认写入 TM，并将 segment 置为 `confirmed`。该操作应幂等：同一 segment 重复确认不能创建重复 TM 条目。

### POST `/projects/{project_id}/segments/{segment_id}/unconfirm`

仅 `manager` 或 `owner` 可撤销确认。撤销不删除 TM 历史条目，而是创建新的 TM 版本或标记为过期。

### POST `/projects/{project_id}/segments/bulk-action`

批量提交审核、QA 或确认。请求体包含 `segment_ids`、`action` 和 `expected_versions`。超过 100 条时返回异步 `job_id`。

## 11. Jobs and audit API

### GET `/jobs/{job_id}`

所有异步导入、解析、导出、索引和批量操作统一通过任务接口查询：

```json
{
  "id": "job-import-123",
  "type": "document_import",
  "status": "running",
  "progress": 0.65,
  "message": "正在解析第 650/1000 个 segment",
  "result": null,
  "error": null,
  "created_at": "2026-09-20T12:00:00Z",
  "finished_at": null
}
```

任务状态：`queued`、`running`、`succeeded`、`failed`、`cancelled`。

### POST `/jobs/{job_id}/cancel`

取消仍处于 `queued` 或 `running` 的可取消任务。

### GET `/projects/{project_id}/audit-events`

查询项目审计日志，支持按用户、资源类型、动作和时间范围筛选。模型输出、术语修改、世界观版本、segment 状态变化和导出都必须记录。

## 12. RAG API boundary

RAG SDK 是平台内部检索能力，不直接承担用户认证、项目隔离或翻译工作流。对前端推荐使用上面的：

```text
POST /projects/{project_id}/tm/search
POST /projects/{project_id}/segments/{segment_id}/suggestions
GET  /projects/{project_id}/context
```

现有验证接口保留为内部开发接口：

```text
POST /api/v1/rag/index
POST /api/v1/rag/search
```

两个验证接口的 JSON 请求体都支持 `project_id` 字段，默认值为 `default`。后端业务层按 `project_id` 隔离进程内索引；project/document 模块应调用后端 RAG 业务函数，不要直接依赖 SDK。

生产实现应将索引绑定到 `project_id`、语言对和版本，并通过异步任务完成重建；不能继续使用当前仅存在于进程内、重启后丢失的索引作为生产存储。

## 13. Recommended implementation order

建议按以下顺序实现，以便每一步都能被前端使用：

1. `auth`：登录、刷新、当前用户和项目权限依赖；
2. `projects`：项目、成员、语言对；
3. `documents` + `segments`：导入、列表、锁定、保存草稿；
4. `terminology` + `worldview`：术语命中和项目上下文；
5. `tm` + `suggestions`：TM/RAG/LLM 建议及证据；
6. `qa` + workflow actions：QA、提交审核、批准、退回、确认；
7. `jobs` + export + audit：异步任务、导出和完整审计；
8. 持久化索引、队列、对象存储和模型供应商适配。

## 14. Current implementation mapping

当前代码目录采用模块化 FastAPI 结构：

```text
src/translation_backend/app/api/modules/
  auth/       认证模块（登录、当前用户和 user API key 子路由）
    api_key/   当前用户自己的 API key 管理
  project/    项目模块（项目资源和 project API key 子路由）
    api_key/   用户 key 与项目的绑定管理
  health/     健康检查
  rag/        RAG 验证接口和 SDK 适配器
```

后续业务模块建议继续按领域拆分：

```text
projects/ documents/ segments/ worldview/ terminology/
translation_memory/ suggestions/ qa/ jobs/ audit/
```

每个模块建议包含 `routes.py`、`schemas.py`、`service.py`，跨模块共享的认证、权限、分页、错误和数据库能力放入 `app/core` 或 `app/api/shared`，避免路由直接操作 SDK、数据库或模型供应商。

## 15. Translation workspace API additions

本节补齐翻译设置、术语管理、任务创建和项目看板的前端所需契约。所有路由均相对于 `/api/v1`。这些接口是前后端的目标契约，**当前后端运行时尚未实现**；界面本地演示适配器不会请求这些 URL。

除只读公开模板目录外，以下接口要求 Bearer access token，并在路由中校验项目成员身份。`owner` 与 `manager` 可管理项目配置、术语、版本、密钥、任务和报表；`translator` 可读取配置/术语、创建和读取翻译任务；`reviewer` 可读取任务和报表；`viewer` 只能读取其项目获准资源。资源不可见时返回 `404`，避免泄露其他项目的 ID。列表沿用 `page_size`（1..100，默认 20）、不透明 `cursor` 和 `{items,next_cursor,total}` 响应格式；可筛选的列表明确列出相应查询字段。

所有写请求支持 `X-Request-ID`。可重试的创建、批量、导入、导出和任务写请求必须带 `Idempotency-Key`。配置更新使用 `If-Match: <revision>` 或请求体 `revision` 做乐观锁；冲突返回 `409 VERSION_CONFLICT` 并携带当前 revision。参数错误使用既有统一错误响应和 `422`。

### 15.1 Translation settings

#### GET `/projects/{project_id}/translation-settings`

读取项目配置，translator 及以上角色可用。成功 `200`：

```json
{
  "project_id": "project-123",
  "revision": 12,
  "worldview": "科幻 RPG 世界观摘要",
  "tone": "中文自然、角色表达有辨识度",
  "updated_at": "2026-09-24T03:00:00Z"
}
```

#### PATCH `/projects/{project_id}/translation-settings`

`owner`/`manager` 更新一个或多个可编辑字段；未提供字段保持不变。请求：

```json
{"revision": 12, "worldview": "新的世界观", "tone": "克制而明快"}
```

返回 `200` 的配置对象（revision 加一）。

#### GET/POST `/projects/{project_id}/translation-settings/roles`

GET 使用分页，可带 `q`；POST 新建角色。角色字段为 `{name,description,detailed_injection,sort_order}`。POST 返回 `201` 和 `{id,project_id,name,description,detailed_injection,revision,created_at,updated_at}`。

#### GET/PATCH/DELETE `/projects/{project_id}/translation-settings/roles/{role_id}`

GET 返回单个角色。PATCH 接受角色字段子集及 `revision`，返回更新角色；DELETE 返回 `204`。写入仅限 `owner`/`manager`。

#### GET/POST `/projects/{project_id}/translation-settings/rules`

规则列表支持 `type=general|category`、`category` 和 `q` 筛选。POST 请求 `{type,name,text,category?,enabled?}`，其中 `type=category` 时 `category` 必填；返回 `201` 规则对象，含 `id`、`revision` 和时间戳。

#### PATCH/DELETE `/projects/{project_id}/translation-settings/rules/{rule_id}`

PATCH 接受 `{revision,type?,name?,text?,category?,enabled?}`，返回更新规则；DELETE 返回 `204`。相同规则不得因重试而重复创建。

#### GET/POST `/projects/{project_id}/translation-settings/culture-rules`

列表支持 `language`、`q` 筛选。POST 请求 `{language,name,text,category?}`；成功 `201` 返回含稳定 `id` 与 `revision` 的文化规则对象。

#### PATCH/DELETE `/projects/{project_id}/translation-settings/culture-rules/{rule_id}`

PATCH 请求包含 `revision` 与需要修改的字段，返回完整规则对象；DELETE 返回 `204`。

#### GET `/translation-templates`

返回平台只读模板目录：`{"items":[{"id":"rpg","name":"游戏本地化 · RPG","description":"..."}]}`。不返回某项目的用户配置或密钥。

#### POST `/projects/{project_id}/translation-settings/initialize`

`owner`/`manager` 使用模板整体初始化项目设置，必须确认替换并发送 `Idempotency-Key`：

```json
{"template_id":"rpg","confirm_replace":true,"expected_revision":12}
```

未确认返回 `422 CONFIRMATION_REQUIRED`；revision 不一致返回 `409`。返回 `200` 完整新配置和递增后的 revision。该操作可审计，不得删除模板目录或项目成员。

### 15.2 Terminology workflows

#### POST `/projects/{project_id}/terminology-bases/{base_id}/terms/import`

`owner`/`manager` 导入 CSV 或 JSON。小型内容请求可用 JSON `{format:"csv",content:"原文,en\\n星门,Star Gate",on_conflict:"update|skip|error"}`；文件上传可用 `multipart/form-data` 字段 `file`，并带 `Idempotency-Key`。同步完成返回 `200` `{created,updated,skipped,invalid_rows:[{row,code,message}]}`；需要后台处理返回 `202` `{job_id,status:"queued"}`。部分无效行不会静默丢弃，响应或 job result 必须保留原始行号和校验原因。

#### POST `/projects/{project_id}/terminology-bases/{base_id}/terms/export`

请求 `{format:"csv|json",language_codes?:["en","ko"],include_disabled:true,filters?:{q,category,required}}`，返回 `200` 文件流（`Content-Disposition` 含安全文件名），大数据集返回 `202` job。导出必须服从项目访问权限，不包含其他项目的条目。

#### POST `/projects/{project_id}/terminology-bases/{base_id}/terms/bulk-action`

`owner`/`manager` 批量操作请求 `{action:"delete|set_required|add_disabled_translation",term_ids:["term-1"],confirm:true,expected_revisions:{"term-1":3},value?:"deprecated term"}`。`term_ids` 限 1..100；破坏性 `delete` 必须 `confirm:true`。返回 `200` `{affected,items:[...]}`，超过 100 条应使用单独异步 job 设计而不是忽略记录。

#### POST `/projects/{project_id}/terminology-bases/{base_id}/terms/clear`

清空整个术语库的破坏性操作，仅 `owner` 可用。请求 `{confirm:true,expected_count:8745}`，必须提供 `Idempotency-Key` 和二次确认；计数不匹配返回 `409 COUNT_MISMATCH`。同步返回 `200` `{deleted:8745}`；规模超出同步阈值则 `202` 返回 job。服务端必须在一个事务或可恢复 job 中完成清空。

#### POST `/projects/{project_id}/terminology/extract`

从项目文件异步提取候选术语。请求 `{file_ids:["file-1"],source_language:"zh-CN",target_languages:["en","ko"],terminology_base_id:"base-1"}`。校验文件属于项目且语言匹配；成功 `202` 返回通用 job 对象，job `type=terminology_extract`。完成结果为 `{candidates:[{source,translations,category,confidence,source_file_id,segment_ids}]}`，默认不自动写入术语库，需用户审阅并通过导入接口提交。

#### POST `/projects/{project_id}/terminology/mine`

从项目 TM 异步挖掘候选术语。请求 `{tm_base_ids:["tm-1"],source_language:"zh-CN",target_languages:["en"],min_occurrences:2,terminology_base_id:"base-1"}`。成功 `202` 返回 `type=terminology_mine` 的通用 job；候选结果包含原文、译文、频次、来源 segment 与置信度，不自动覆盖已审核词条。

### 15.3 Versions, files and provider keys

#### GET/POST `/projects/{project_id}/versions`

GET 支持 `q`、游标分页和 `sort=created_at|name`。POST（`owner`/`manager`）请求 `{name,description?,source_language?,target_languages?}`，返回 `201` `{id,project_id,name,description,created_at,created_by}`。同项目版本名称冲突返回 `409 VERSION_NAME_EXISTS`。

#### GET `/projects/{project_id}/versions/{version_id}/files`

返回该版本内可用源文件的分页 `{items:[{id,name,source_language,format,updated_at,size_bytes}],next_cursor,total}`。无版本文件时返回空列表而非 404；版本不属于当前项目时按资源不可见返回 `404`。

#### GET/POST `/projects/{project_id}/api-keys`

项目 API key 接口只管理“用户 key 与项目的绑定关系”，不保存、不接收也不返回 secret。仅 `owner`/`manager` 可管理绑定；项目成员只能看到当前项目已授权使用的脱敏 key 元数据。

GET 返回项目绑定列表：

```json
{
  "items": [
    {
      "id": "project-key-binding-456",
      "api_key_id": "user-key-123",
      "provider": "openai",
      "label": "工作账号",
      "masked_secret": "sk-proj-••••••••1234",
      "status": "active",
      "is_default": true,
      "created_at": "2026-09-24T03:05:00Z"
    }
  ],
  "next_cursor": null,
  "total": 1
}
```

POST 将当前用户拥有的 key 绑定到项目，请求 `{api_key_id,is_default?}`。服务端必须校验该 key 属于当前用户、状态为 `active`，且调用方有权管理该项目；成功返回 `201` 绑定对象。绑定同一 key 的重试请求必须幂等；尝试绑定不属于当前用户的 key 返回 `404`，不得泄露其他用户的 key 是否存在。

#### PATCH/DELETE `/projects/{project_id}/api-keys/{binding_id}`

PATCH 只修改 `{status,is_default}`，同一项目最多一个 `is_default=true` 的绑定；DELETE 只解除项目绑定并返回 `204`，不会删除用户自己的 key。若绑定被活动翻译任务引用，删除返回 `409 API_KEY_IN_USE`。项目删除时绑定关系级联删除，但用户级 key 保留。

API key secret 的安全要求适用于用户级 POST 和后端调用链路：生产环境只能通过 HTTPS/TLS 传输；服务端收到 secret 后必须在持久化前使用 AES-256-GCM 加密，只将密文、唯一 nonce/IV 和外部加密密钥版本写入数据库；AES 主密钥必须由数据库外的 KMS 或受控 secret manager 管理，并支持密钥轮换。仅在向 provider 发起请求前由受限后端短暂解密，任何响应、日志、审计、追踪、错误信息和导出均不得包含明文 secret。该方案是 TLS 加应用层静态加密，不是严格 E2E；后端代用户调用 provider 时必须能够解密。

### 15.4 Translation tasks

#### GET/POST `/projects/{project_id}/translation-tasks`

GET 支持 `source_language`、`target_language`、`status=queued|translating|review|completed`、`version_id`、`q`、游标分页。POST（`owner`、`manager`、`translator`）请求：

```json
{
  "name":"版本公告英韩翻译",
  "source_language":"zh-CN",
  "target_languages":["en","ko"],
  "file_ids":["file-1","file-2"],
  "project_api_key_id":"project-key-binding-456",
  "version_id":"version-12"
}
```

名称、至少一个目标语言、至少一个属于该项目且源语言一致的文件，以及有效项目 API key 绑定为必填；`version_id` 可省略。目标语言不能等于源语言，目标列表不得重复。任务只引用 `project_api_key_id`，返回项目绑定 ID 与脱敏的 provider/label，不返回用户 key 原文。请求须带 `Idempotency-Key`。成功 `201` 返回 `{id,project_id,name,source_language,target_languages,file_ids,version_id,project_api_key:{id,api_key_id,provider,label,masked_secret},status:"queued",progress:0,created_at}`。校验失败返回 `422` 字段错误。

#### GET `/projects/{project_id}/translation-tasks/{task_id}`

返回完整任务元数据、状态、进度、文件数、目标语言、版本和脱敏的模型凭据引用。状态定义为 `queued`、`translating`、`review`、`completed`、`failed`、`cancelled`；`progress` 范围 0..100。客户端不能通过 PATCH 任意伪造进度或越过工作流状态。

### 15.5 Analytics

#### 15.5.1 Token usage data model

每次调用 AI provider 完成后写入一条不可变的 `ai_usage_records` 明细。该表是 token 用量和成本统计的唯一事实来源，当前不建立日聚合表；接口查询时按 `completed_at` 在 PostgreSQL 中聚合。

核心字段如下：

| 字段 | 类型/约束 | 说明 |
| --- | --- | --- |
| `id` | UUID 主键 | 用量事件 ID |
| `user_id` | UUID，可空 | 用户 ID 快照，用户删除后仍保留历史统计 |
| `project_id` | UUID，可空 | 项目 ID 快照；用户级调用为空 |
| `api_key_id` | UUID，可空 | 用户 API key ID 快照，不使用会级联删除历史的外键 |
| `project_api_key_binding_id` | UUID，可空 | 项目 API key 绑定 ID 快照 |
| `provider` | string | 调用时的 provider 快照 |
| `model` | string | 调用时的模型标识 |
| `provider_request_id` | string，可空 | provider 请求 ID；与 `provider` 组合用于幂等去重 |
| `status` | enum | `succeeded`、`failed`、`timeout` |
| `input_tokens` | non-negative bigint | 输入 token 数 |
| `output_tokens` | non-negative bigint | 输出 token 数 |
| `cached_input_tokens` | non-negative bigint | 缓存命中的输入 token 数 |
| `reasoning_tokens` | non-negative bigint | 推理 token 数，provider 未提供时为 0 |
| `total_tokens` | non-negative bigint | 总 token 数，通常等于输入与输出等 provider 计费字段之和 |
| `cost` | non-negative decimal(20,8) | 调用成本，不使用浮点数存储 |
| `currency` | ISO 4217 string | 成本货币，默认 `USD` |
| `started_at` | UTC timestamp，可空 | 调用开始时间 |
| `completed_at` | UTC timestamp | 成功、失败或超时的完成时间，也是趋势分桶时间 |
| `latency_ms` | integer，可空 | 调用耗时 |
| `error_code` | string，可空 | 失败或超时错误码，成功时为空 |

明细表不得保存 prompt、completion、secret 或其他模型输入输出原文。建议建立 `(user_id, completed_at)`、`(project_id, completed_at)`、`(api_key_id, completed_at)`、`(provider, model, completed_at)` 索引，并按 `completed_at` 范围查询。数据量达到较大规模后，可对明细表按月分区或增加物化视图，但不改变本 API 契约。

#### 15.5.2 GET `/auth/me/analytics/usage`

返回当前用户所有 API key 的用量总览。只允许访问当前用户自己的统计；支持以下查询参数：

```text
range=7d|30d                    # 与 from/to 二选一，默认 7d
from=2026-09-18T00:00:00Z      # 闭区间起点
to=2026-09-24T23:59:59Z        # 闭区间终点
timezone=Asia/Shanghai          # 趋势分桶时区，默认 UTC
granularity=day|hour            # 默认 day；hour 最多查询 7 天
api_key_id=user-key-123         # 可选
project_id=project-123          # 可选
provider=openai                 # 可选
model=gpt-5.6-luna              # 可选
```

`day` 粒度最多查询 31 天；服务端必须拒绝超出范围的请求，避免无界扫描。成功 `200`：

```json
{
  "range": {
    "from": "2026-09-18T00:00:00Z",
    "to": "2026-09-24T23:59:59Z",
    "timezone": "Asia/Shanghai",
    "granularity": "day"
  },
  "totals": {
    "call_count": 13917,
    "success_count": 13880,
    "failure_count": 37,
    "input_tokens": 10655434,
    "output_tokens": 852591,
    "cached_input_tokens": 120000,
    "reasoning_tokens": 62000,
    "total_tokens": 11508025,
    "cost": "57.40800000",
    "currency": "USD"
  },
  "trend": [
    {
      "bucket_start": "2026-09-20T00:00:00+08:00",
      "calls": 180,
      "success_calls": 178,
      "failed_calls": 2,
      "input_tokens": 82000,
      "output_tokens": 15000,
      "total_tokens": 97000,
      "cost": "4.29000000",
      "currency": "USD"
    }
  ],
  "by_api_key": [
    {
      "api_key_id": "user-key-123",
      "provider": "openai",
      "label": "工作账号",
      "masked_secret": "sk-proj-••••••••1234",
      "calls": 13619,
      "input_tokens": 10593413,
      "output_tokens": 805997,
      "total_tokens": 11399410,
      "cost": "57.34500000",
      "currency": "USD"
    }
  ],
  "by_model": [
    {
      "provider": "openai",
      "model": "gpt-5.6-luna",
      "calls": 13619,
      "input_tokens": 10593413,
      "output_tokens": 805997,
      "total_tokens": 11399410,
      "cost": "57.34500000",
      "share": 0.9989,
      "currency": "USD"
    }
  ]
}
```

`trend` 必须按时间升序返回，并补齐没有调用的日期或小时为 0，供前端绘制 token/cost 双轴折线图。`totals` 包含成功、失败和超时记录；若 provider 对失败请求返回了部分用量，应保留对应 token 和 cost。成本字段以字符串返回，避免前端浮点精度丢失。

#### 15.5.3 GET `/projects/{project_id}/analytics/usage`

返回当前项目的 token 用量总览，权限遵循项目报表读取权限。除 `range`、`from`、`to`、`timezone`、`granularity`、`provider`、`model` 外，支持：

```text
project_api_key_id=project-key-binding-456
api_key_id=user-key-123
```

服务端必须校验筛选的 key 属于该项目的绑定关系，不能通过参数探测其他项目或用户的 key。响应结构与 `/auth/me/analytics/usage` 相同，但 `by_api_key` 只包含该项目绑定且在查询范围内产生调用的 key。

前端可使用 `totals` 渲染顶部指标卡，使用 `trend` 绘制“每日用量与成本”双轴折线图，使用 `by_model` 或 `by_api_key` 渲染明细表。图表示例中的数值仅为展示数据，不属于接口固定值。

#### 15.5.4 Redis usage and caching boundary

Redis 不是用量事实来源，也不是必需依赖。调用完成后应先将 `ai_usage_records` 写入 PostgreSQL，再由查询接口按时间聚合。

当统计查询频繁或明细量较大时，可以使用 Redis 缓存聚合响应：

- 缓存 key 必须包含用户或项目 ID、完整筛选条件、时间范围、时区和粒度；
- TTL 建议 30 至 120 秒，允许图表出现短暂延迟；
- 新增明细后可删除相关用户/项目缓存，也可以接受 TTL 内的最终一致性；
- Redis 不得替代 PostgreSQL 明细，不得只把 token 增量写入 Redis 后丢弃明细；
- Redis 不可用时接口应回退到 PostgreSQL 查询，不影响用量记录的写入。

如果未来单表查询无法满足性能要求，优先考虑 `completed_at` 分区或 PostgreSQL 物化视图；增加日聚合表属于后续性能优化，不是当前 API 的必要组成部分。

#### GET `/projects/{project_id}/analytics/translation-report`

筛选参数：`from`、`to`（闭区间 ISO 日期）、`target_language`、`status`。返回 `200` `{filters:{...},summary:{task_count,translated_words},daily:[{date,task_count,translated_words}]}`。无记录时返回零汇总与空 `daily`。过滤只影响当前项目，并且统计的 `translated_words` 定义以服务端实现统一采用的词数策略为准；计数不应伪装成模型调用或 token 用量。

### 15.6 Runtime boundary

以上新增路径是 API 契约，不表示当前 FastAPI 已具备相应 handler、数据库表、任务队列、AI 服务或聚合查询。部署前必须分别实现后端路由/schema/service、项目权限、迁移与后台 job，并用 HTTP 集成测试逐路由验证；仅文档检查或本地演示适配器测试不构成后端可用性证明。
