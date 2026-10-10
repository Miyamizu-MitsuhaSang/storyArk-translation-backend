# StoryArk Translation Backend

StoryArk 的 FastAPI 后端，提供认证、项目工作区、CAT 工作流、翻译任务、AI provider 用量统计，以及基于独立 RAG SDK 的稀疏向量检索接口。外部 LLM/provider 默认关闭，只有配置 provider、加密主密钥和可用网络后才会由 worker 调用。

## 当前接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/v1/auth/login` | 登录并获取令牌 |
| `POST` | `/api/v1/auth/refresh` | 刷新令牌 |
| `POST` | `/api/v1/auth/logout` | 撤销刷新令牌 |
| `GET` | `/api/v1/auth/me` | 获取当前用户 |
| `PATCH` | `/api/v1/auth/me/password` | 修改当前用户密码 |
| `POST` | `/api/v1/rag/index` | 构建当前进程的 RAG 索引 |
| `POST` | `/api/v1/rag/search` | 检索索引中的文档 |
| `GET` | `/api/v1/auth/me/translation-memories` | 当前用户 TM 库列表 |
| `POST` | `/api/v1/projects/{project_id}/tm/search` | exact/fuzzy TM 检索 |
| `POST` | `/api/v1/projects/{project_id}/translation-memories/reindex` | 提交 TM 索引重建任务 |
| `GET` | `/api/v1/jobs/{job_id}` | 查询 TM 索引任务状态 |
| `GET/PATCH` | `/api/v1/projects/{project_id}/segments/{segment_id}` | CAT 片段详情与草稿保存 |
| `POST/DELETE` | `/api/v1/projects/{project_id}/segments/{segment_id}/lock` | CAT 片段锁定、释放和续租 |
| `POST` | `/api/v1/projects/{project_id}/segments/{segment_id}/suggestions` | TM、术语库和世界观建议 |
| `POST` | `/api/v1/projects/{project_id}/segments/{segment_id}/qa` | CAT 片段 QA 检查 |
| `POST` | `/api/v1/projects/{project_id}/segments/{segment_id}/submit-review` | 提交审核 |
| `POST` | `/api/v1/projects/{project_id}/segments/{segment_id}/approve` | 审核通过 |
| `POST` | `/api/v1/projects/{project_id}/segments/{segment_id}/reject` | 审核退回 |
| `POST` | `/api/v1/projects/{project_id}/segments/{segment_id}/confirm` | 确认并写入 TM |
| `POST` | `/api/v1/projects/{project_id}/segments/bulk-action` | 批量工作流动作 |
| `GET` | `/api/v1/auth/me/analytics/usage` | 当前用户 AI provider 用量统计 |
| `GET` | `/api/v1/projects/{project_id}/analytics/usage` | 项目 AI provider 用量统计 |
| `GET` | `/api/v1/projects/{project_id}/analytics/translation-report` | 项目翻译报告零汇总占位接口 |

完整 API 契约见 [`docs/api.md`](docs/api.md)。翻译记忆当前提供用户库 CRUD、项目有效范围、精确/fuzzy 检索、异步重建和任务状态查询；analytics 统计以 PostgreSQL 明细为事实来源，Redis 只作可选短 TTL 缓存；运行时路由以 `/docs` 和 `/openapi.json` 为准。

## TM 功能说明

翻译记忆（TM）以 PostgreSQL 中的库和条目为事实来源。索引产物只是可重建的检索加速层，不能替代 TM 数据。每个库有递增的 `content_version`；条目新增、修改或归档后版本变化，旧版本索引不能覆盖新版本索引。

### 数据和权限

- `platform` 库为公共库，`user` 库只属于创建者。
- 项目成员关系决定项目可见 TM 范围；请求不能通过 `include_library_ids` 越权读取其他用户的库。
- 只索引 `status=active` 且 `deleted_at` 为空的条目。
- 条目保留语言、原文、译文、来源、修订号和受控 metadata；metadata 禁止保存 token、secret、API key、prompt 或 completion。

### 检索模式

`POST /api/v1/projects/{project_id}/tm/search` 的 `match_mode` 有两种：

- `exact`：默认模式，使用 PostgreSQL 规范化原文哈希精确检索。没有 worker、索引产物或 Redis 时仍可用。
- `fuzzy`：要求库存在与当前 `content_version`、格式版本和 vectorizer 版本匹配的活动产物。服务端先验证项目权限和库范围，再选择完整源语言/目标语言分区，调用 RAG SDK Top-K，最后回查仍 active 的 TM 条目。

`fuzzy` 产物缺失、过期、checksum 不匹配、格式不兼容或文件不可读时返回 `503 INDEX_NOT_AVAILABLE`，不会使用旧缓存伪造结果。`503` 响应带 `Retry-After: 5`。当前不提供 dense semantic 检索。

### 索引重建生命周期

1. 启用 `TM_INDEX_TASKS_ENABLED=true` 后，reindex 请求为每个有效库捕获当前 `content_version`。
2. dispatcher 按 `(任务类型, 库 ID, requested_version)` 幂等创建 `BackgroundJob`，Celery task ID 使用 job UUID。
3. worker 以短租约领取任务；同一 job 不能被两个未过期 worker 同时执行。
4. worker 按语言对构建确定性 TF-IDF 非负稀疏向量，序列化 RAG SDK 索引，写入内容寻址文件并校验 SHA-256。
5. 发布前锁定库再次检查 `content_version`。版本不匹配时产物标记为 `superseded`，不会替换活动索引。
6. 存储异常使用有界指数退避重试，达到上限后任务为 `failed`；之前的活动产物保留。
7. worker 租约过期后由恢复任务重新投递。Celery Beat 每 60 秒回收过期 TM index job。

任务状态接口只返回 job ID、类型、状态、请求版本、尝试次数、脱敏结果和脱敏错误，不返回文件路径、storage URI、原文或原始异常。

### 持久化产物

本地存储使用 `TM_INDEX_STORAGE_DIR/sha256/<sha256>`，文件名只由内容 SHA-256 生成。写入过程使用临时文件、flush、fsync 和原子重命名；读取时再次计算 checksum，并执行大小限制。路径 API 拒绝 `..`、非 SHA-256 URI 和其他不可信路径。

Celery Beat 每小时运行历史产物清理：

- 永不删除 `active`、`building`、`ready` 产物。
- 不删除仍被 queued/running job 引用的产物。
- `superseded` 和 `failed` 产物按 `TM_INDEX_RETENTION_COUNT` 保留最新历史，其余同时删除文件和数据库记录。

运行指标目前是进程内计数器，包含队列延迟、构建耗时、重试、过期构建丢弃、产物加载失败、清理删除和 SQL 检索回退。它们尚未接入外部 Prometheus exporter；多进程部署时需要后续改为共享指标后端。

## 环境要求

- Python 3.13 或更高版本
- [`uv`](https://docs.astral.sh/uv/)
- PostgreSQL
- Git 和可用的 C++17 编译器，用于构建独立的 RAG SDK
- Redis 可选；`.env.app` 中的 `REDIS_ENABLED` 默认为 `false`

`translate-manager-rag` 位于仓库内的 `packages/translate-manager-rag/`，通过本地 editable 依赖安装。它只负责非负稀疏向量的倒排索引和 Top-K MIPS 检索；threshold 属于索引配置，不需要每次搜索重复传入，`top_k` 属于查询参数且默认值为 5。

## 配置

应用从 `src/translation_backend/env/` 读取 `.env.app`、`.env.db` 和 `.env.security`。先创建这些本地文件，并替换示例密码和密钥：

`src/translation_backend/env/.env.app`：

```dotenv
APP_NAME=translation-platform
API_PREFIX=/api/v1
LOG_LEVEL=INFO
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
# Redis 总开关与连接地址；具体功能还需打开对应功能开关
REDIS_ENABLED=false
REDIS_URL=redis://127.0.0.1:6379/2
TM_CACHE_ENABLED=false
TM_CACHE_NAMESPACE=tm
# Redis 短时防止同一 Idempotency-Key 并发执行；数据库仍是幂等事实来源
IDEMPOTENCY_REDIS_ENABLED=false
IDEMPOTENCY_LOCK_TTL_SECONDS=300
IDEMPOTENCY_REDIS_NAMESPACE=idempotency
TM_SEARCH_MAX_TEXT_LENGTH=4096
TM_SEARCH_MAX_PAGE_SIZE=50
# false 时 reindex API 返回 503；true 时启用 Celery TM 索引任务投递
TM_INDEX_TASKS_ENABLED=false
TM_INDEX_STORAGE_DIR=var/tm-indexes
TM_INDEX_MAX_ARTIFACT_BYTES=536870912
TM_INDEX_RETENTION_COUNT=3
# RAG 候选筛选阈值；0 保证非负稀疏权重下不丢失低权重累积匹配
RAG_CANDIDATE_THRESHOLD=0.0
# 各语种模型独立开关；默认关闭，关闭时只用后端分词器和 TF-IDF
TM_SEMANTIC_MODEL_ZH_ENABLED=false
TM_SEMANTIC_MODEL_EN_ENABLED=false
TM_SEMANTIC_MODEL_JA_ENABLED=false
TM_SEMANTIC_MODEL_ZH_PATH=models/semantic/bge-small-zh-v1.5
TM_SEMANTIC_MODEL_EN_PATH=models/semantic/bge-small-en-v1.5
TM_SEMANTIC_MODEL_JA_PATH=models/semantic/ruri-base
# 文档源文件本地存储目录、单文件大小上限和删除宽限期
DOCUMENT_STORAGE_DIR=var/documents
DOCUMENT_MAX_FILE_BYTES=52428800
DOCUMENT_PURGE_GRACE_SECONDS=86400
# true 时由 Celery worker 自动领取导入、解析、导出和清理任务
DOCUMENT_TASKS_ENABLED=false
# true 时由 Celery worker 执行超过 100 条的 CAT 批量工作流任务
CAT_TASKS_ENABLED=false
```

启用 `DOCUMENT_TASKS_ENABLED=true` 后，Celery worker 处理文档导入、解析、导出任务；Celery Beat 每小时运行 `documents.cleanup_due`，只清理已超过 `DOCUMENT_PURGE_GRACE_SECONDS` 且没有活动任务引用的软删除文档。清理失败会保留数据库记录和存储标识，并依靠 `BackgroundJob` 的有限重试机制处理，不会直接删除文档事实记录。

后端也兼容已有环境文件中的 `CANDIDATE_THRESHOLD`；两个变量同时存在时优先使用 `RAG_CANDIDATE_THRESHOLD`。

### TM 语句处理与语义模型

处理器默认使用后端内置 tokenizer 和 TF-IDF 生成非负稀疏向量，不需要下载模型或安装模型依赖。三个语种开关彼此独立；仅打开对应开关时才会惰性加载本地语义模型。模型生成的稠密 embedding 会先经确定性随机超平面哈希转换为非负稀疏向量，以适配 `translate-manager-rag`；原始稠密向量不会传入 SDK。该哈希是角度相似度的近似，不等同于 SDK 原生 dense cosine；模型模式仍需召回质量评测后才能用于生产。

当前 TM reindex worker 和 `fuzzy` 检索使用确定性稀疏向量化与本地持久化索引；`SentenceProcessor` 的可选语义模型开关不会自动改变 TM worker 的默认 TF-IDF 构建。下载模型是显式准备步骤，程序运行时只从配置目录加载，不会隐式联网。模型文件较大且受各自模型卡许可约束，下载和使用前请阅读模型卡： [BGE 中文](https://huggingface.co/BAAI/bge-small-zh-v1.5)、[BGE 英文](https://huggingface.co/BAAI/bge-small-en-v1.5)、[Ruri 日文](https://huggingface.co/cl-nagoya/ruri-base)。

先安装可选模型依赖和 Hugging Face CLI：

```bash
uv sync --extra semantic
```

从后端目录分别下载需要的模型。下载路径需与 `.env.app` 中相应的 `TM_SEMANTIC_MODEL_<LANG>_PATH` 一致；不开启某语种时可跳过该模型：

```bash
uv run hf download BAAI/bge-small-zh-v1.5 --local-dir models/semantic/bge-small-zh-v1.5
uv run hf download BAAI/bge-small-en-v1.5 --local-dir models/semantic/bge-small-en-v1.5
uv run hf download cl-nagoya/ruri-base --local-dir models/semantic/ruri-base
```

完成下载后，在 `.env.app` 中仅将需要启用的语种开关设为 `true`。模型目录位于 Git 忽略路径 `models/semantic/`，请勿提交模型权重。

`src/translation_backend/env/.env.db`：

```dotenv
DB_USER=postgres
DB_PASSWORD=change-me
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=translation_platform
```

`src/translation_backend/env/.env.security`：

```dotenv
AUTH_JWT_SECRET=replace-with-a-random-secret
AUTH_ACCESS_TOKEN_TTL_SECONDS=900
AUTH_REFRESH_TOKEN_TTL_DAYS=30
AUTH_API_KEY_ENCRYPTION_KEY=replace-with-a-32-byte-base64-key
AUTH_API_KEY_ENCRYPTION_KEY_VERSION=v1
```

启动前需准备好 PostgreSQL 数据库及模型所需的数据表，并执行 Aerich 迁移：

```bash
uv run aerich upgrade
```

Redis 和 Celery 是可选的。Redis 的总开关和连接地址统一配置在 `.env.app`：只有 `REDIS_ENABLED=true` 且对应功能开关（例如 `TM_CACHE_ENABLED` 或 `IDEMPOTENCY_REDIS_ENABLED`）开启时，应用才会建立 Redis 客户端连接。Redis 不可用时，TM 查询和幂等流程分别降级到无缓存查询和 PostgreSQL 唯一约束；Redis 不作为事实来源。`TM_INDEX_STORAGE_DIR` 保存本地内容寻址索引产物，`TM_INDEX_RETENTION_COUNT` 控制历史产物保留数量；清理任务不会删除活动、构建中或仍被任务引用的产物。需要异步导入或重建索引时，另起 Celery worker，并确保 `CELERY_BROKER_URL` 和 `CELERY_RESULT_BACKEND` 可访问：

```bash
uv run celery -A app.tasks.celery_app:celery_app worker --loglevel=INFO
```

不要把真实的数据库密码或 JWT 密钥提交到 Git。

## 本地运行

```bash
uv sync --locked
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

服务启动后可打开 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

基础连通性任务为 `translation_backend.app.tasks.health.ping`，可作为后续异步业务任务的模板。

## TM 验证命令

在 `src/translation_backend` 目录运行：

```bash
# 全量后端回归
uv run pytest -q

# TM 单元、worker、索引、HTTP、维护和重启恢复测试
uv run pytest tests/test_translation_memory_* -q

# 第 15 章工作区、任务和 analytics 验收
uv run pytest tests/test_translation_workspace_* tests/test_terminology_workflows.py \
  tests/test_project_versions_api.py tests/test_translation_tasks_* tests/test_usage_analytics_* -q

# Python 编译和空白差异检查
uv run python -m compileall -q app main.py
git diff --check
```

测试使用临时 SQLite、临时 artifact store 和 Celery eager/任务替身验证核心行为，包括：TM 条目写入、exact 查询、索引构建、fuzzy 查询、checksum 拒绝、版本竞争、任务租约、重试、过期任务回收、产物清理和进程重启后的活动产物加载。它们不能替代真实 PostgreSQL、Redis、Celery broker、文件权限和多进程部署验证。

Task 8 的验收还覆盖第 15 章 OpenAPI 路径、响应模型、`Idempotency-Key`、用户级 API key 脱敏、项目版本创建、analytics 权限隔离和跨项目 `404`。`translation-report` 当前仅提供权限校验后的零汇总占位结果；真实词数统计属于后续实现范围。

启用真实服务后，建议依次运行：

```bash
uv run pytest -q
uv run aerich heads
uv run aerich upgrade
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/openapi.json >/tmp/translation-openapi.json
```

然后设置 `TM_INDEX_TASKS_ENABLED=true`，启动 Celery worker 和 Beat，提交一次 reindex，轮询 `/api/v1/jobs/{job_id}`，再使用 `match_mode=fuzzy` 验证结果。`/health` 成功只说明进程可响应；PostgreSQL、Redis、Celery、TM 索引和外部模型仍需分别检查。不要把文档同步或容器启动成功当作业务接口已完成的证明。

在当前源码布局中，Aerich 需要通过项目运行入口提供 `TORTOISE_ORM` 配置；如果直接在 `src/translation_backend` 目录执行 `uv run aerich heads` 报配置加载错误，应先按部署入口注入配置，再在备份的 PostgreSQL 验证库执行 migration。SQLite 测试不会证明 PostgreSQL migration、Redis 连接、Celery broker、真实 provider、TLS 终止或生产签名配置可用。

## Docker

从仓库根目录构建并运行：

```bash
docker build -t storyark-translation-backend .
docker run --rm -p 8000:8000 \
  --env-file src/translation_backend/env/.env.app \
  --env-file src/translation_backend/env/.env.db \
  --env-file src/translation_backend/env/.env.security \
  storyark-translation-backend
```

容器内的 `DB_HOST` 必须指向容器可访问的 PostgreSQL 地址；不要在连接宿主机数据库时使用容器自身的 `127.0.0.1`。
