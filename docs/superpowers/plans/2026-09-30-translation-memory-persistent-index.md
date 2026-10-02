# 翻译记忆持久化索引实施计划

> **执行说明：** 建议使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`，按任务逐项执行本计划。步骤使用 `- [ ]` 复选框跟踪进度。

**目标：** 构建可在进程重启后恢复、能够识别版本的 TM 索引 worker，持久化 RAG SDK 索引产物，同时保留 PostgreSQL 事实来源和 SQL 精确检索回退。

**架构：** PostgreSQL 保存后台任务、索引产物和 `content_version`；Celery worker 构建不可变的版本化稀疏索引；第一阶段使用本地文件系统保存产物，后续替换为兼容 S3 的对象存储；只有版本匹配、校验通过并完成原子发布的产物才能用于 fuzzy 检索。原始稠密语义检索不在此计划范围内。

**技术栈：** Python 3.13、FastAPI、Tortoise ORM、Aerich、PostgreSQL、Celery/Redis、pytest、`translate-manager-rag`。

**设计文档：** `docs/superpowers/specs/2026-09-30-translation-memory-persistent-index-design.md`

## 全局约束

- PostgreSQL 中的 TM 条目和 `content_version` 始终是事实来源。
- Redis 只作为可选结果缓存，不能作为权威索引存储。
- 即使没有 worker 或索引产物，SQL 精确检索也必须可用。
- 过期 worker 绝不能用旧产物覆盖更新版本的库索引。
- 所有持久化错误和日志都必须脱敏并限制长度。
- 产物路径只能使用程序生成的 UUID/哈希部分。
- 每项任务先编写失败测试，再实现代码，最后运行针对性测试。
- 不修改工作树中已有的无关认证、项目、术语或前端改动。
- 每项任务通过后，只提交该任务列出的文件。

## 测试环境约定

后端测试复用异步 SQLite fixture：初始化 `translation_backend.app.models`、生成 schema，并在 teardown 时关闭 Tortoise 连接。共享 fixture 提供 `make_user()`、`make_project_with_owner()`、`make_library(content_version=1)`、`make_artifact(library, content_version)`、`service_with_local_store(tmp_path)`、`bump_library_version(library_id, version)` 和 `make_search_service()`。SDK 测试只使用公开 SDK 构造器和 `serialize()` 返回的字节。

---

## 阶段 0：固定契约与迁移边界

### 任务 0：固定设计契约

**文件：** 阅读设计文档；必要时修改 `docs/api.md`；测试 `tests/test_translation_memory_api.py`。

**产出：** 固定 `BackgroundJob`、`TranslationMemoryIndexArtifact`、`IndexArtifactStore`、`TranslationMemoryIndexBackend` 和 `TranslationMemoryIndexService` 的名称及职责。

- [x] 编写契约失败测试，确认 reindex 响应包含 `job_id`、`status`、`requested_version` 和 `type=tm_index_rebuild`。
- [x] 运行：`uv run pytest tests/test_translation_memory_api.py -q`，确认当前响应不完整。
- [x] 更新设计/API 文档中的响应结构，不在本任务实现 handler。
- [x] 再次运行测试并确认通过。

## 阶段 1：持久化基础与任务生命周期

### 任务 1：新增通用后台任务模型

**文件：** 新建 `app/models/jobs.py`；修改 `app/models/__init__.py`；新建 `migrations/models/7_20260930190000_add_background_jobs.py`；测试 `tests/test_translation_memory_jobs.py`。

**接口：** `BackgroundJob.claim()`、`BackgroundJob.complete()`、`BackgroundJob.fail()`；字段包括 `type`、`status`、`resource_type`、`resource_id`、`requested_version`、`attempts`、`max_attempts`、租约和错误信息。

- [x] 测试同一任务只能被一个 worker 领取。
- [x] 运行：`uv run pytest tests/test_translation_memory_jobs.py -q`，确认模型和状态转换尚不存在。
- [x] 使用 `select_for_update` 实现领取、租约过期回收、成功、失败和重试上限。
- [x] 为 `(status, available_at)` 与 `(resource_type, resource_id, requested_version)` 建索引。
- [x] 运行测试，确认所有状态转换通过。

### 任务 2：新增 TM 索引产物模型

**文件：** 修改 `app/models/translation_memory.py`、`app/models/__init__.py`；新建 `migrations/models/8_20260930191000_add_tm_index_artifacts.py`；测试 `tests/test_translation_memory_artifacts.py`。

**接口：** `TranslationMemoryIndexArtifact`，以 `(library_id, content_version, format_version)` 唯一标识，状态包括 `building`、`ready`、`active`、`superseded`、`failed`。

- [x] 编写过期版本不能发布的失败测试。
- [x] 运行：`uv run pytest tests/test_translation_memory_artifacts.py -q`。
- [x] 增加 `storage_uri`、`checksum`、`vectorizer_version`、`row_count`、`feature_count`、任务关联和失败原因。
- [x] 用事务锁定库记录；只有当前库版本等于产物版本时才激活产物，并将旧产物标记为 `superseded`。
- [x] 验证唯一性、活动产物替换和过期版本拒绝。

## 阶段 2：SDK 持久化与确定性向量化

### 任务 3：增加 SDK 公开序列化 API

**文件：** 修改 `../../packages/translate-manager-rag/translate_manager_rag/native.py`、`retriever.py`，新增 `persistence.py`；测试 `../../packages/translate-manager-rag/tests/test_persistence.py`。

**接口：** `TopKMipsIndex.serialize()`、`TopKMipsIndex.deserialize(payload)`、`SparseMipsRetriever.serialize()`、`SparseMipsRetriever.deserialize(payload)`。

- [x] 先编写索引序列化往返测试。
- [x] 运行 `tests/test_persistence.py`，确认新 API 尚不存在。
- [x] 实现带魔数、格式版本、维度和校验的封装；只持久化稀疏行和 JSON 文档 metadata，加载时重建 native 索引，不使用 pickle。
- [x] 保持现有 `build/search/clear` 行为不变。
- [x] 重建 SDK native 扩展并运行 SDK 全套测试。
- [x] 将通过测试的 SDK 更新推送到 `storyArk-rag-sdk` 的 `main`，并验证远端 SHA。

### 任务 4：实现后端确定性向量化器

**文件：** 使用 `app/infrastructure/translation_memory/sentence_processing.py` 中的向量化器；新建 `app/infrastructure/translation_memory/index_format.py`；测试 `tests/test_translation_memory_sentence_processing.py` 和 `tests/test_translation_memory_index_format.py`。

**接口：** `TranslationMemoryVectorizer(version)`、`fit(entries: Iterable[tuple[str, str]])`、`encode(text, language) -> list[tuple[int, float]]`，以及包含词汇表和分词元数据的索引封装。默认使用后端多语言 tokenizer + 非负 TF-IDF；语言级语义开关默认关闭，开启时语义 embedding 必须先转换为 SDK 可接受的非负稀疏特征。

- [x] 测试相同文本产生相同向量并验证 `version`；复用已有 `sentence_processing.py` 实现和测试。
- [x] 运行 `tests/test_translation_memory_sentence_processing.py` 和 `tests/test_translation_memory_index_format.py`。
- [x] 实现词汇表、文档频率、tokenizer/vectorizer 版本及 SDK 索引的校验封装；特征 ID 排序稳定，向量无重复/负权重。
- [x] 加载时要求精确匹配 `expected_vectorizer_version`，版本变化时拒绝解释旧产物。

## 阶段 3：产物存储与 worker

### 任务 5：增加索引产物存储抽象

**文件：** 新建 `app/infrastructure/translation_memory/artifact_store.py`；修改 `app/core/config.py`；测试 `tests/test_translation_memory_artifact_store.py`。

**接口：** `IndexArtifactStore.put_atomic()`、`open()`、`delete()`、`exists()`、`checksum()`；实现 `LocalIndexArtifactStore(root: Path)`；增加 `tm_index_storage_dir`、`tm_index_max_artifact_bytes`、`tm_index_retention_count` 配置。

- [x] 测试内容寻址、原子写入和路径穿越防护。
- [x] 运行：`uv run pytest tests/test_translation_memory_artifact_store.py -q`。
- [x] 使用临时文件、flush/fsync、原子重命名、大小限制和校验和验证。
- [x] 存储失败抛出类型化异常，供 worker 重试。

### 任务 6：实现版本化 TM 索引构建和发布

**文件：** 新建 `app/application/translation_memory/index_service.py`；修改 `app/infrastructure/translation_memory/search_index.py`、`app/application/translation_memory/service.py`；测试 `tests/test_translation_memory_index_service.py`。

**接口：** `TranslationMemoryIndexBackend.build()`、`serialize()`、`deserialize(payload)`、`search()`；`TranslationMemoryIndexService.enqueue_rebuild()`、`build_job()`、`load_active()`、`publish_if_current()`。

- [x] 编写库版本在构建期间变化时不得发布的失败测试。
- [x] 运行：`uv run pytest tests/test_translation_memory_index_service.py -q`。
- [x] 按语言对分别读取活动且未删除的 TM 条目，生成各自的稀疏向量、SDK retriever 和条目 ID 映射，封装到同一版本产物中；查询必须先选中语言对分区再执行 Top-K。
- [x] 写入产物并计算校验和；发布前再次检查 `content_version`。
- [x] 验证成功构建、重复任务、校验失败、版本过期和活动产物替换。

### 任务 7：接入 Celery 领取、重试和恢复

**文件：** 修改 `app/tasks/translation_memory.py`、`app/tasks/celery_app.py`、`app/application/translation_memory/service.py`；测试 `tests/test_translation_memory_worker.py`。

**接口：** `rebuild_translation_memory_index_task(job_id)`、`TranslationMemoryTaskDispatcher.enqueue_rebuild()`、`reclaim_expired_index_jobs()`。

- [x] 编写存储临时故障触发重试的失败测试。
- [x] 运行：`uv run pytest tests/test_translation_memory_worker.py -q`。
- [x] 使用任务 ID 作为确定性 Celery task ID，事务领取租约，并实现指数退避和重试上限。
- [x] 让重复投递安全，确保旧版本构建和 worker 崩溃可恢复。
- [x] 验证 eager 成功、重试、重复投递、租约回收、过期构建和最终失败。

## 阶段 4：API 集成与精确检索回退

### 任务 8：暴露任务状态并接入 reindex 响应

**文件：** 修改 `app/api/modules/project/project_content/translation_memory/routes.py`、`app/api/router.py`、`app/application/translation_memory/schemas.py`；新建或修改 `app/api/modules/jobs/routes.py`；测试 `tests/test_translation_memory_http.py`。

**接口：** `POST /api/v1/projects/{project_id}/translation-memories/reindex` 返回 `202`；`GET /api/v1/jobs/{job_id}` 返回任务状态、请求版本、尝试次数及脱敏结果。

- [x] 测试 broker 或存储不可用时返回 `503 INDEX_NOT_AVAILABLE`。
- [x] 运行：`uv run pytest tests/test_translation_memory_http.py -q`。
- [x] 实现成员权限检查、`202/503` 语义和任务状态脱敏；不暴露文件路径、存储 URI、原文或原始异常。
- [x] 确保 exact 查询在语义索引不可用时仍可用。

### 任务 9：加载活动产物并开放后续检索模式

**文件：** 修改 `app/application/translation_memory/service.py`、`app/infrastructure/translation_memory/search_index.py`、`app/application/translation_memory/schemas.py`；测试 `tests/test_translation_memory_search_modes.py`。

**接口：** 仅在 schema 启用且存在兼容活动产物时支持稀疏向量 `match_mode=fuzzy`。真正的模型语义检索不属于本计划；若后续开放该能力，须单独设计并验证 dense-to-sparse 投影质量或扩展 SDK dense-vector 能力。

- [x] 测试缺少活动产物时 fuzzy 检索返回 `TranslationMemoryIndexUnavailableError`。
- [x] 运行：`uv run pytest tests/test_translation_memory_search_modes.py -q`。
- [x] 先验证项目有效库和权限，再按请求语言对选择独立分区，校验产物版本、格式版本、向量化器版本后调用 SDK。
- [x] 将 SDK 命中行映射回 TM 响应；过期或损坏产物返回 `503`。

## 阶段 5：清理、监控和部署

### 任务 10：增加产物清理和运行指标

**文件：** 新建 `app/tasks/translation_memory_maintenance.py`；修改 `app/tasks/__init__.py`、`app/core/config.py`、`README.md`；测试 `tests/test_translation_memory_maintenance.py`。

**接口：** `cleanup_superseded_artifacts()`；指标包括队列延迟、构建耗时、重试数、过期构建丢弃数、产物加载失败数和 SQL 回退数。

- [x] 测试保留活动产物、运行中任务引用产物和配置数量的历史产物。
- [x] 运行：`uv run pytest tests/test_translation_memory_maintenance.py -q`。
- [x] 禁止删除活动、构建中或被任务引用的产物。
- [x] 补充 `TM_INDEX_STORAGE_DIR`、重试次数、保留数量和产物大小限制说明。

### 任务 11：增加部署与重启恢复冒烟测试

**文件：** 修改 `README.md`；必要时修改 `docker-compose.yml`；新建 `tests/test_translation_memory_restart.py` 和 `tests/fixtures/tm_index_artifact/`。

- [x] 测试进程重启后可加载活动产物，无需重新构建。
- [x] 运行：`uv run pytest tests/test_translation_memory_restart.py -q`。
- [x] 分别检查数据库、artifact store、SDK 格式兼容性和 Celery broker；索引未就绪不能阻止 API 进程启动。
- [x] 运行完整后端测试并验证 worker 重启后的租约恢复。

## 阶段 6：共享对象存储与规模化

### 任务 12：增加兼容 S3 的产物存储

**文件：** 新建 `app/infrastructure/translation_memory/object_store.py`；修改 `app/application/translation_memory/index_service.py`、`app/core/config.py`；测试 `tests/test_translation_memory_object_store.py`。

- [ ] 测试 `S3IndexArtifactStore` 与 `IndexArtifactStore` 协议一致。
- [ ] 运行：`uv run pytest tests/test_translation_memory_object_store.py -q`。
- [ ] 实现临时对象键、上传、远端校验和、本地有界读取缓存和清理。
- [ ] 不改变任务发布语义，只通过依赖注入替换存储实现。

### 任务 13：增加规模化保护

**文件：** 修改 `app/infrastructure/translation_memory/vectorizer.py`、`app/application/translation_memory/index_service.py`、`app/tasks/translation_memory_maintenance.py`；测试 `tests/test_translation_memory_scale_limits.py`。

- [ ] 测试超过内存或条目预算时抛出 `IndexResourceLimitError`。
- [ ] 运行：`uv run pytest tests/test_translation_memory_scale_limits.py -q`。
- [ ] 实现有界批处理、worker 内存限制、单库并发限制和背压指标。
- [ ] 只有在显式配置后才按语言对或库分片，不能悄悄改变结果顺序。

## 最终验收

- [ ] SDK 测试：`uv run --project ../../packages/translate-manager-rag pytest -q`。
- [ ] 后端测试：`uv run pytest -q`。
- [ ] 编译检查：`uv run python -m compileall -q app main.py`。
- [ ] 差异检查：`git diff --check`。
- [ ] 在临时 PostgreSQL 上执行 Aerich 迁移。
- [ ] 启动 API 和 Celery worker，提交重建任务，重启 worker，验证租约恢复。
- [ ] 构建期间修改 TM 库，确认旧版本产物不会被发布。
- [ ] 无索引产物时确认 exact 查询可用，fuzzy 查询返回 `503`。
- [ ] 确认产物和日志不包含凭据、API key 或未经脱敏的异常。
- [ ] 确认最终 API 文档与生成的 OpenAPI 路径和响应描述一致。
