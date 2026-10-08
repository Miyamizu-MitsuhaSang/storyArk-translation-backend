# StoryArk 翻译平台数据库描述

本文档描述后端计划使用的 PostgreSQL 数据模型，重点说明第 8 章文档导入、归档和文件清理相关的数据边界。它是数据库设计说明，不代表对应 ORM 模型、迁移和后台任务已经全部实现。

## 1. 数据职责

PostgreSQL 保存业务事实和生命周期元数据；文件本体保存于受控的本地文件目录或兼容 S3 的对象存储。数据库不保存上传文件的二进制内容，也不向 API 返回服务器绝对路径。

```text
Document.storage_key
  -> 本地存储：DOCUMENT_STORAGE_DIR/<storage_key>
  -> 对象存储：bucket/key
```

`storage_key` 必须由服务端根据项目 ID 和文档 ID 生成，例如：

```text
projects/{project_id}/documents/{document_id}/source.xliff
```

请求中的文件名只能作为展示字段保存，不能直接拼接为文件系统路径。

## 2. 核心表

### 2.1 `documents`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | UUID | 主键 | 稳定的文档业务 ID，即 API 的 `document_id` |
| `project_id` | UUID | 非空，外键 | 所属项目；所有读取和写入都必须按项目校验权限 |
| `name` | varchar(255) | 非空 | 项目内展示名称 |
| `original_filename` | varchar(512) | 非空 | 上传时的原始文件名，仅作展示和审计 |
| `format` | varchar(32) | 非空 | `xliff`、`csv`、`json`、`po`、`txt` 等受支持格式 |
| `source_language` | varchar(16) | 非空 | 源语言 BCP 47 标签 |
| `target_language` | varchar(16) | 非空 | 目标语言 BCP 47 标签 |
| `status` | varchar(32) | 非空 | 文档生命周期状态 |
| `storage_key` | varchar(1024) | 可空 | 文件的逻辑存储键；清理完成后可保留用于追踪，禁止存绝对路径 |
| `size_bytes` | bigint | 非空 | 文件大小 |
| `checksum` | char(64) | 非空 | 文件内容 SHA-256，用于完整性检查和幂等判断 |
| `version` | integer | 非空，默认 1 | 文档元数据/文件版本 |
| `created_by` | UUID | 非空，外键 | 上传用户 |
| `created_at` | timestamptz | 非空 | 创建时间 |
| `updated_at` | timestamptz | 非空 | 最近更新时间 |
| `archived_at` | timestamptz | 可空 | 归档时间 |
| `deleted_at` | timestamptz | 可空 | 软删除请求时间 |
| `purge_after` | timestamptz | 可空 | 允许物理清理的时间 |
| `purged_at` | timestamptz | 可空 | 文件实际清理完成时间 |
| `error_code` | varchar(64) | 可空 | 最近一次导入/解析/清理失败代码 |
| `error_message` | varchar(512) | 可空 | 脱敏后的失败信息，不保存原始异常或秘密 |

建议状态：

```text
uploaded -> parsing -> ready
                     \-> failed
ready -> archived
uploaded|ready|failed|archived -> deletion_pending -> purged
```

`parsing`、`exporting` 或仍被有效后台任务引用的文档不能直接进入 `purged`。`purged` 表示文件本体已清理，不表示数据库记录必须删除。

建议索引：

- `(project_id, status, updated_at)`：项目文档列表和状态筛选；
- `(project_id, original_filename)`：文件名筛选；
- `(project_id, source_language, target_language)`：语言对筛选；
- `(status, purge_after)`：清理 worker 扫描待清理文档；
- `checksum`：重复文件检测或幂等上传辅助查询。

### 2.2 `segments`

`segments.document_id` 为非空外键，指向 `documents.id`。文档删除操作不能级联物理删除 segments；文档进入 `deletion_pending` 或 `purged` 后，segments 仍用于审计、版本追踪和 TM 来源引用。是否允许工作台读取已归档文档由项目权限和接口状态规则决定。

建议字段包括 `id`、`document_id`、`segment_no`、`source`、`target`、`source_language`、`target_language`、`status`、`workflow_state`、`version`、锁信息和时间戳。`(document_id, segment_no)` 应建立唯一约束。

CAT 工作台额外使用以下字段和表：

- `translator_note`：当前译员备注；
- `qa_results`、`qa_checked_at`：最近一次 QA 摘要和检查时间；
- `change_history`：受限长度的状态/版本变更摘要；
- `segment_locks`：短期编辑租约，按 `segment_id` 唯一；
- `segment_suggestions`：TM、术语库和世界观建议的文本、来源、分数、证据和警告快照。

本版本不在 CAT 接口中调用外部 LLM/provider；`segment_suggestions.provider` 默认记录为 `internal`，后续接入 provider 时再增加对应 adapter 和用量记录。

### 2.3 `background_jobs`

现有通用后台任务表可复用于文档导入、解析、导出和清理：

```text
type: document_import | document_parse | document_export | document_purge
resource_type: document
resource_id: documents.id
requested_version: documents.version
```

CAT 超大批量工作流使用 `type=cat_bulk_action`、`resource_type=project`，请求快照保存在脱敏 `result` 中，由 `CAT_TASKS_ENABLED` 控制是否派发 Celery worker。

任务必须记录状态、尝试次数、租约、完成时间、脱敏结果和错误信息。清理 worker 领取任务前应重新检查文档状态、`purge_after`、版本和任务引用，防止旧任务删除新版本文件。

### 2.4 `document_file_events`（建议）

如果需要完整存储操作审计，建议增加文件事件表，而不是覆盖 `documents` 的历史字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID | 事件 ID |
| `document_id` | UUID | 文档 ID |
| `event_type` | varchar(32) | `uploaded`、`archived`、`delete_requested`、`purged`、`purge_failed` |
| `storage_key` | varchar(1024) | 事件发生时的逻辑键 |
| `checksum` | char(64) | 事件发生时的文件校验和 |
| `actor_user_id` | UUID，可空 | 发起用户；定时 worker 为空或使用 worker 标识 |
| `job_id` | UUID，可空 | 关联后台任务 |
| `metadata` | JSONB | 受控非敏感元数据 |
| `created_at` | timestamptz | 事件时间 |

该表只追加，不因文件物理清理而删除。

## 3. 文件清理规则

清理采用“软删除 + 宽限期 + 异步物理删除”：

1. API 设置 `deleted_at` 和 `purge_after`，状态改为 `deletion_pending`；
2. worker 只扫描已到 `purge_after` 的记录；
3. worker 确认没有解析、导出或其他活动任务引用；
4. 删除对象存储文件或本地文件，并校验删除结果；
5. 成功后写入 `purged_at`，失败则保留 `storage_key` 并按策略重试。

当前 worker 入口为 `documents.cleanup_due`，由 Celery Beat 每小时触发。worker 每次只扫描已经到达 `purge_after` 的 `deletion_pending` 文档；如果文档仍有导入、解析或导出任务处于 `queued/running`，本轮跳过，下一轮重新检查。每个清理操作都会复用或创建一个 `document_purge` 类型的 `BackgroundJob`，通过任务租约避免多个 worker 同时删除同一文件。

建议默认保留期限：

| 对象 | 默认期限 |
| --- | --- |
| 未完成上传临时文件 | 24 小时 |
| 导出临时文件 | 24 至 72 小时 |
| 用户请求删除的源文件 | 24 小时宽限期 |
| 归档文件 | 30 至 90 天，按部署策略配置 |

期限必须通过配置提供，不能在 SQL 中写死。存在法律保留、项目锁定或活动任务时应暂停清理。

## 4. 事务和一致性

- 创建 `Document` 记录与导入任务时使用同一业务事务；文件写入使用临时键，成功后再切换为最终 `storage_key`。
- 文件删除不是数据库事务的一部分，必须通过任务状态和事件记录处理失败与重试。
- 清理任务使用文档 `version` 或 checksum 做乐观校验，旧任务不得删除新上传版本。
- 数据库记录、segments、TM 来源和审计事件的保留策略独立于文件本体清理。
- Redis 只能作为清理扫描或任务调度的辅助组件，不能作为文档、文件或删除状态的事实来源。

## 5. API 幂等记录

`api_idempotency_records` 保存可重试写请求的幂等键、请求指纹和首次成功响应。唯一约束为 `(user_id, idempotency_key)`；相同 key 用于不同操作、资源范围或请求参数时拒绝重放。Redis 可选地以 `SET NX EX` 建立短时处理中锁，减少同 key 并发落入业务执行；锁释放通过 Lua 比对随机 token，避免删除其他请求持有的锁。Redis 未启用或不可用时回退数据库唯一约束，最终响应仍只以 PostgreSQL 记录为准。

## 5. 迁移顺序

实现第 8 章运行时接口时，建议按以下顺序生成迁移：

1. 创建 `documents` 表和项目/用户外键；
2. 创建 `segments` 表或为现有 segments 增加 `document_id` 外键；
3. 为 `background_jobs` 增加文档任务类型约束（如由应用层维护则无需数据库枚举）；
4. 如需完整文件审计，再创建 `document_file_events`；
5. 部署本地存储 adapter 和清理 worker 后，再开启 `DELETE` 接口。

在 ORM、迁移和 worker 完成前，API 文档中的 document 接口仍属于目标契约，不能宣称已可用。
