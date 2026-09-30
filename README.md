# StoryArk Translation Backend

StoryArk 的 FastAPI 后端，提供认证、健康检查，以及基于独立 RAG SDK 的稀疏向量检索接口。当前 RAG 索引保存在进程内存中，进程重启后需要重新构建。

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

完整 API 契约见 [`docs/api.md`](docs/api.md)。翻译记忆当前提供用户库 CRUD、项目有效范围、精确检索和异步重建；文档中标记为规划的导入、模糊/语义检索和工作流接口需要以后端路由及集成测试为准。运行时路由以 `/docs` 和 `/openapi.json` 为准。

## 环境要求

- Python 3.13 或更高版本
- [`uv`](https://docs.astral.sh/uv/)
- PostgreSQL
- Git 和可用的 C++17 编译器，用于构建独立的 RAG SDK
- Redis 可选；`REDIS_LAUNCH` 默认为 `false`

`translate-manager-rag` 从 [storyArk-rag-sdk](https://github.com/Miyamizu-MitsuhaSang/storyArk-rag-sdk) 的 `main` 分支安装；SDK 源码不包含在本仓库中。

## 配置

应用从 `src/translation_backend/env/` 读取 `.env.app`、`.env.db` 和 `.env.security`。先创建这些本地文件，并替换示例密码和密钥：

`src/translation_backend/env/.env.app`：

```dotenv
APP_NAME=translation-platform
API_PREFIX=/api/v1
LOG_LEVEL=INFO
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
TM_CACHE_ENABLED=false
TM_CACHE_NAMESPACE=tm
TM_SEARCH_MAX_TEXT_LENGTH=4096
TM_SEARCH_MAX_PAGE_SIZE=50
```

`src/translation_backend/env/.env.db`：

```dotenv
DB_USER=postgres
DB_PASSWORD=change-me
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=translation_platform
REDIS_LAUNCH=false
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

Redis 和 Celery 是可选的。启用 `REDIS_LAUNCH=true` 后，应用连接 `127.0.0.1:6379`；设置 `TM_CACHE_ENABLED=true` 才会使用 Redis TM 检索缓存，Redis 不可用时自动降级为无缓存查询。需要异步导入或重建索引时，另起 Celery worker，并确保 `CELERY_BROKER_URL` 和 `CELERY_RESULT_BACKEND` 可访问：

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

部署检查建议依次运行：

```bash
uv run pytest -q ../../tests
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/openapi.json >/tmp/translation-openapi.json
```

`/health` 成功只说明进程可响应；PostgreSQL、Redis、Celery、TM 索引和外部模型仍需分别检查。不要把文档同步或容器启动成功当作业务接口已完成的证明。

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
