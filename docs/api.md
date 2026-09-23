# Translation Platform API

通用 CAT/AI 翻译平台 API 设计草案。本文档描述第一版业务 API 契约，作为 FastAPI 路由、Pydantic Schema 和前端 API client 的共同依据。

当前后端已实现健康检查、认证和基础 RAG 验证接口。本文档还描述项目、文档、segment、术语、TM、审核和导出等后续接口，设计先以通用游戏本地化 CAT 平台为目标，后续可以根据实际业务删减字段。

## 文档源与同步

`api-contract/docs/api.md` 是平台仓库中的 API 文档源文件；本仓库保留供后端使用的同步副本。平台源文件和前端副本不包含在本仓库中：

```text
docs/api.md
```

修改 API 契约时，请在平台仓库更新源文件并同步后，再将后端副本更新到本仓库。

当前运行接口以本服务的 FastAPI OpenAPI 文档为准；本文件中尚未实现的接口属于契约规划。

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
app/api/modules/
  auth/       用户认证接口和服务
  health/     健康检查
  rag/        RAG 验证接口和 SDK 适配器
```

后续业务模块建议继续按领域拆分：

```text
projects/ documents/ segments/ worldview/ terminology/
translation_memory/ suggestions/ qa/ jobs/ audit/
```

每个模块建议包含 `routes.py`、`schemas.py`、`service.py`，跨模块共享的认证、权限、分页、错误和数据库能力放入 `app/core` 或 `app/api/shared`，避免路由直接操作 SDK、数据库或模型供应商。
