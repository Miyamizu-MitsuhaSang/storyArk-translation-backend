# 项目级 Settings API 设计

## 1. 目标与范围

本设计为项目级工作流配置增加独立的 settings 资源和 API，并明确它与用户级设置、现有项目翻译设置的边界。

本期包含三个互不混合的作用域：

1. 用户级设置：`/api/v1/auth/me/settings`，只保存当前用户的外观主题和界面语言。
2. 项目级 settings：`/api/v1/projects/{project_id}/settings`，保存项目工作流默认值和开关。
3. 项目翻译设置：`/api/v1/projects/{project_id}/translation-settings`，继续保存世界观、语气、角色、翻译规则和文化规则。

本期不迁移现有 `translation-settings` 数据，不把三类设置合并到 JSON 表，也不允许用户级接口修改项目配置。

## 2. 设计决策

### 2.1 独立资源和 API 章节

项目级 settings 使用独立的 `project_settings` 路由模块、`application/project/settings` 用例包、模型和文档章节。路由标签使用 `project-settings`，用户级路由保持 `auth-settings`，现有翻译设置保持 `translation-settings`。

这样 OpenAPI、权限审计和前端数据适配器都能按作用域查找，不会将用户偏好和项目业务配置混为同一接口。

### 2.2 第一版字段

`ProjectSettings` 是每个项目一条记录，字段全部显式类型化：

- `default_source_language`：默认源语言标签，可为空；必须属于项目已配置的源语言集合。
- `default_target_language`：默认目标语言标签，可为空；必须属于项目已配置的目标语言集合。
- `terminology_enabled`：是否在项目工作流中启用术语规则，默认 `true`。
- `translation_memory_enabled`：是否在项目工作流中启用翻译记忆，默认 `true`。
- `default_model`：项目默认 AI 模型标识，可为空；只保存模型 ID，不保存供应商密钥或明文凭据。
- `quality_threshold`：质量阈值，范围 `0..1`，默认 `0.7`。
- `revision`：乐观并发版本，默认 `1`。

默认语言字段允许为空，表示由具体任务显式选择；如果只提交其中一个字段，服务层拒绝不完整的默认语言对，避免产生无效项目默认值。

### 2.3 权限和隔离

- 所有项目成员可以读取项目 settings。
- 只有 `owner` 或 `manager` 可以更新项目 settings。
- 非成员统一返回项目不可见的 `404`，成员但无写权限返回 `403`。
- 请求体不接收 `project_id` 或用户 ID；主体由路径和当前认证用户确定。
- 项目删除时 settings 记录级联删除。

### 2.4 并发控制

`PATCH /projects/{project_id}/settings` 使用现有项目 `expected_revision` 规则：优先读取 `If-Match`，也兼容请求体 `revision`。版本不匹配返回 `409 VERSION_CONFLICT` 并携带当前版本；成功更新后 `revision` 加一。空 PATCH 返回当前完整对象，不增加版本。

## 3. 数据模型

新增 `project_settings` 表：

- `id`：UUID 主键；
- `project_id`：指向 `projects.id` 的一对一外键，唯一且级联删除；
- `default_source_language`：`VARCHAR(16)`，可空；
- `default_target_language`：`VARCHAR(16)`，可空；
- `terminology_enabled`：`BOOLEAN NOT NULL DEFAULT TRUE`；
- `translation_memory_enabled`：`BOOLEAN NOT NULL DEFAULT TRUE`；
- `default_model`：`VARCHAR(160)`，可空；
- `quality_threshold`：`DOUBLE PRECISION NOT NULL DEFAULT 0.7`，数据库约束 `0 <= value <= 1`；
- `revision`：`INT NOT NULL DEFAULT 1`，数据库约束 `revision >= 1`；
- `created_at`、`updated_at`：统一时间字段。

服务层首次读取时创建默认记录。更新语言字段前读取项目语言对，确保语言属于项目配置；更新模型只接受非空、长度受限的模型 ID，不处理 API key。

## 4. 后端分层

- `app/models/project_settings.py`：只定义 ORM 映射和字段描述。
- `app/application/project/settings/schemas.py`：请求/响应 schema、字段范围和响应模型。
- `app/application/project/settings/service.py`：项目成员读取、管理员写入、默认记录创建、语言对校验和 revision 冲突。
- `app/api/modules/project/settings/routes.py`：独立路由、OpenAPI tags、错误映射和 `If-Match` 解析。
- `app/api/router.py`：显式注册 project settings router。
- `main.py`：注册 project settings 异常处理器。
- `migrations/models/<next>_add_project_settings.py`：新增表、约束和索引。

路由不直接查询 ORM；项目权限复用 `require_project_member`/`require_project_role` 或等价的 application 层授权方法。

## 5. API 契约

### 5.1 读取项目级 settings

`GET /api/v1/projects/{project_id}/settings`

项目成员可调用，返回：

```json
{
  "project_id": "project-uuid",
  "default_source_language": "zh-CN",
  "default_target_language": "en-US",
  "terminology_enabled": true,
  "translation_memory_enabled": true,
  "default_model": "gpt-4.1-mini",
  "quality_threshold": 0.7,
  "revision": 1,
  "updated_at": "2026-10-13T00:00:00Z"
}
```

### 5.2 更新项目级 settings

`PATCH /api/v1/projects/{project_id}/settings`

请求体字段全部可选；只更新出现的字段：

```json
{
  "revision": 1,
  "default_source_language": "zh-CN",
  "default_target_language": "en-US",
  "terminology_enabled": true,
  "translation_memory_enabled": false,
  "default_model": "gpt-4.1-mini",
  "quality_threshold": 0.8
}
```

返回更新后的完整 settings 对象。语言不属于项目语言集合返回 `422`；非管理员返回 `403`；revision 不匹配返回 `409`；未登录返回 `401`。

## 6. 前端契约

前端 `DataAdapter` 增加独立方法：

```ts
getProjectSettings(): Promise<ProjectSettings>;
updateProjectSettings(input: ProjectSettingsUpdate): Promise<ProjectSettings>;
```

`remoteAdapter` 调用 `/projects/${projectId}/settings`，`localAdapter` 维护同结构的本地种子数据。用户设置仍调用 `/auth/me/settings`；现有项目翻译设置方法继续调用 `/translation-settings` 及其子资源。

## 7. 文档和同步

在 `api-contract/docs/api.md` 新增独立章节“项目级 Settings API”，章节位置紧邻项目基础 API，但不得放入“用户设置”章节或将其标题合并。修改后从仓库根目录运行 `./scripts/sync-api-docs.sh`，同步到后端和 `src/storyark_frontend/docs/api.md` 等四个副本；使用 `./scripts/check-api-docs.sh` 验证副本一致和新路径存在。

## 8. 测试与验收

- ORM/迁移：一对一唯一约束、默认值、质量阈值约束、项目删除级联。
- 服务：首次读取默认记录、成员可读、管理员可写、普通成员写入拒绝、非成员隔离、语言集合校验、部分更新和 revision 冲突。
- API：OpenAPI 独立 tag/路径、GET/PATCH、`If-Match`、`401/403/404/409/422` 错误结构。
- 回归：用户 settings 路由仍仅出现在 `auth-settings`；translation-settings 路由和已有数据行为不变。
- 前端：remote/local adapter 方法、项目设置保存、未知响应字段兼容和文档副本同步。

验收只声明本地代码和 SQLite/测试数据库证据；PostgreSQL、Redis、Celery、真实 AI provider 和部署环境另行报告。
