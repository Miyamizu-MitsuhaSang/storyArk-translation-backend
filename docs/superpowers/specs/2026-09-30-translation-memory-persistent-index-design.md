# 翻译记忆持久化索引设计

## 状态

本文提出翻译记忆（TM）持久化索引 worker 的设计，是实施计划 `docs/superpowers/plans/2026-09-30-translation-memory-persistent-index.md` 的设计依据。

## 目标

为 TM 库增加可在进程重启后恢复、能够识别版本的后台索引流程，同时继续以 PostgreSQL 为事实来源、Redis 仅作可选缓存，并保留精确 SQL 查询作为可靠回退路径。

## 当前状态

- TM 库及其条目通过 Tortoise ORM 持久化到 PostgreSQL。
- 每个库都有单调递增的 `content_version`。
- 精确检索通过原文规范化哈希和数据库过滤实现。
- Celery 已完成配置，并已处理大批量 TM 导入。
- 目前没有持久化索引后端，因此 `TranslationMemoryTaskDispatcher.enqueue_rebuild()` 会抛出 `RuntimeError`。
- 当前集成的 `translate-manager-rag` SDK 提供内存态的 `TopKMipsIndex` 和 `SparseMipsRetriever` 构建、查询操作，但没有稳定的持久化或加载接口。
- Redis 仅用于有界的检索结果缓存，不是索引事实来源。

## 方案决策

采用混合式、带版本的索引产物架构：

1. PostgreSQL 继续作为 TM 数据的权威存储，并记录库版本、任务和索引产物元数据。
2. Celery worker 针对一个 `library_id` 和一个 `content_version` 构建完整且不可变的索引快照。
3. 第一阶段使用可配置的本地文件系统目录存放索引产物，适用于开发环境和单机部署。存储接口应允许未来替换为兼容 S3 的实现，而不改动应用服务。
4. RAG SDK 提供带版本的持久化封装，其中包含序列化索引、向量化器元数据、文档到条目的映射和校验和。SDK 必须提供明确的保存/加载接口；后端代码不能依赖 native 对象的私有实现细节。
5. 索引产物只有在校验和验证通过、并由数据库事务原子发布后才能用于查询。旧内容版本的 worker 绝不能覆盖更新版本的活动索引。
6. 精确 TM 查询继续使用 SQL。模糊或语义查询只有在存在兼容的活动索引产物时才使用该产物；否则返回文档约定的 `503 INDEX_NOT_AVAILABLE`，不能悄悄使用过期语义结果。

## 数据模型

### 后台任务

新增精简且可复用的 `BackgroundJob` 模型，用于 TM 索引以及未来的文档、术语任务：

- `id`：UUID 主键。
- `type`：稳定的任务类型，例如 `tm_index_rebuild`。
- `status`：`queued`、`running`、`succeeded`、`failed` 或 `cancelled`。
- `resource_type` 和 `resource_id`：逻辑资源，初期为 `translation_memory_library` 及其 UUID。
- `requested_version`：提交任务时记录的库 `content_version`。
- `attempts`、`max_attempts`、`available_at`、`started_at`、`finished_at`。
- `worker_id` 和 `lease_expires_at`：用于回收崩溃 worker 遗留的任务。
- `result`：JSON 结果元数据，包含产物 ID 和行数，不得包含秘密信息。
- `error_code` 和 `error_message`：长度受限且已脱敏的失败详情。
- `created_at` 和 `updated_at`。

该模型有意设计为通用模型，但本功能只实现 TM 索引任务行为。其他任务类型以后可以复用该模型。

### TM 索引产物

新增 `TranslationMemoryIndexArtifact` 模型：

- `id`：UUID。
- `library_id`：指向 TM 库的外键。
- `content_version`：构建时使用的不可变源数据版本。
- `status`：`building`、`ready`、`active`、`superseded` 或 `failed`。
- `storage_uri`：索引产物存储位置的不透明标识；绝不能使用不可信请求文本拼接路径。
- `checksum`：完整索引封装的 SHA-256 校验和。
- `format_version`：索引产物格式版本。
- `vectorizer_version`：确定性向量化器版本。
- `row_count` 和 `feature_count`。
- `build_job_id`、`built_at`、`activated_at` 和 `failure_reason`。

对 `(library_id, content_version, format_version)` 设置唯一约束，并保证每个库最多只有一个活动产物。发布时必须使用事务：仅当库仍处于任务请求的 `content_version` 时，才将旧活动产物降级并激活新产物。

## Worker 数据流

1. `POST /projects/{project_id}/translation-memories/reindex` 验证项目成员身份，并确定当前有效库。
2. 对每个库读取当前 `content_version`，按 `(type, resource_id, requested_version)` 幂等地创建或复用 `BackgroundJob`。
3. dispatcher 将任务 ID 提交给 Celery，并以 `202` 返回任务引用。如果 broker 或产物存储不可用，则返回 `503 INDEX_NOT_AVAILABLE`，不能记录虚假的成功状态。
4. worker 通过短时租约领取任务。其他 worker 不能同时处理仍在有效租约内的同一任务。
5. worker 读取请求版本下活动且未删除的 TM 条目一致性快照，生成确定性稀疏向量，并构建 SDK 索引及条目元数据映射。
6. worker 将封装写入临时产物，执行 fsync/flush，计算校验和，再原子重命名到最终的内容寻址位置。
7. 在数据库事务中确认库版本仍等于 `requested_version`。如果版本已改变，则将任务标记为 `superseded` 并为新版本创建任务；不得发布过期产物。
8. 如果版本未变，则将产物标记为 `ready`，更新库的活动产物指针，将任务标记为 `succeeded`，并将旧产物标记为 `superseded`。
9. 失败时记录脱敏错误、增加尝试次数，并按有界指数退避策略重试。达到重试上限后将任务标记为 `failed`，保留之前的活动产物。

## 查询行为

- 访问索引产物前必须先执行权限校验和有效库过滤。
- `match_mode=exact` 继续使用数据库查询；即使没有 worker 或索引产物，也必须可用。
- 未来的 `fuzzy` 和 `semantic` 模式要求存在活动产物，且产物库及 `content_version` 与数据库版本一致。
- 低于当前版本的产物属于过期产物，不能用于语义结果。
- 对于必须使用索引的模式，产物缺失、损坏、不兼容或不可用时返回 `503 INDEX_NOT_AVAILABLE`。
- Redis 缓存键继续包含用户、项目、查询过滤条件、库 ID 和内容版本。发布产物时清理受影响的缓存项。

## SDK 契约

扩展 `translate-manager-rag`，提供公开且带版本的持久化 API；后端不得自行序列化 pybind 对象：

- `TopKMipsIndex.serialize() -> bytes` and `TopKMipsIndex.deserialize(payload: bytes) -> TopKMipsIndex`.
- `SparseMipsRetriever.serialize() -> bytes` and `SparseMipsRetriever.deserialize(payload: bytes) -> SparseMipsRetriever`.
- 封装记录 `sdk_version`、`format_version`、`feature_count`、行数和文档元数据。
- 加载时先校验魔数、格式版本、维度和校验和，再允许索引用于查询。
- 现有内存态 `build/search/clear` 行为保持向后兼容。

后端负责文本到稀疏向量的适配器，以及带版本的词汇表/分词元数据。向量化器变更时必须提升 `vectorizer_version` 并重建索引，不能用新规则重新解释旧产物。

## 存储演进

### 第一阶段：本地索引产物存储

使用 `TM_INDEX_STORAGE_DIR` 存储按库、按版本组织的内容寻址文件。该方案支持本地开发和单 worker 主机。文件系统实现必须使用临时文件、原子重命名、校验和验证、产物大小限制和安全清理。

### 第二阶段：共享对象存储

为兼容 S3 的存储实现同一存储协议。worker 上传到临时对象键，验证远端校验和后再发布数据库元数据。API worker 通过有界本地缓存加载产物。

### 第三阶段：扩展能力与保留策略

保留活动产物和可配置数量的历史产物；只删除已被替代且没有运行中任务引用的产物。数据量确有需要时，再按库或语言分片。

## API 与运维

- 保留 `POST /projects/{project_id}/translation-memories/reindex`，以 `202` 返回任务引用。
- 新增或复用 `GET /jobs/{job_id}`，返回状态、尝试次数、请求版本、产物结果和脱敏错误详情。
- 增加内部健康/就绪检查，分别检查数据库、Celery broker、产物存储和 SDK 加载能力；不能将进程健康等同于索引就绪。
- 记录任务 ID、库 ID、请求版本、活动版本、耗时、行数、产物校验和及失败代码。不得记录原文、API key 或未经处理的元数据。
- 暴露队列延迟、构建耗时、过期构建丢弃数、重试数、产物加载失败数、缓存命中率和 SQL 回退次数等指标。

## 故障与恢复规则

- worker 崩溃：租约过期后允许其他 worker 重新领取任务。
- broker 故障：提交时返回 `503`，不能返回误导性的排队成功结果。
- 存储故障：任务失败并按策略重试；保留最后一个活动产物。
- 构建期间数据库版本变化：放弃发布并为新版本创建任务。
- 产物损坏：隔离产物、标记失败，并在支持的情况下使用 SQL 精确检索回退。
- 部署回滚：旧版本应用仍可使用 SQL 精确检索；产物格式版本可阻止加载不兼容数据。

## 安全与隐私

- 读取索引产物元数据或结果前，必须验证作用域和项目成员关系。
- 产物路径和对象键只能由 UUID、哈希生成，不能使用用户提供的名称。
- 产物封装只包含检索所需的 TM 文本、语言元数据、向量化数据和条目 ID；不能包含 API key 或 prompt/completion 内容。
- 限制条目数、文本大小、产物大小和 worker 内存用量。
- 持久化或返回异常信息前必须脱敏。

## 验证策略

- 单元测试覆盖序列化往返、校验和拒绝、向量化确定性、租约处理、过期版本保护、重试策略和原子发布。
- 使用 SQLite/PostgreSQL 兼容 schema 编写集成测试，覆盖任务/产物状态转换和版本竞争。
- 使用 Celery eager 模式测试构建成功、重试、失败和重新入队。
- API 测试覆盖 `202`、`503`、任务状态、权限隔离和精确查询回退。
- SDK 测试保留在 SDK 仓库中；后端启用集成前必须先通过。
- 运维冒烟测试覆盖 worker 启动、产物存储权限、数据库迁移和重启恢复。

## 非目标

- 不将 Redis 用作权威索引存储。
- 不使用索引产物文件替代 PostgreSQL 中的 TM 数据。
- 在兼容的向量化器和 SDK 持久化加载能力就绪前，不启用语义检索。
- 第一版 worker 不实现文档解析、术语挖掘或无关的通用任务。
