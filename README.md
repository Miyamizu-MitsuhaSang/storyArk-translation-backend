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

完整 API 契约见 [`docs/api.md`](docs/api.md)。契约还包含尚未实现的项目、文档、术语、翻译记忆和审核等规划接口；运行时路由以 `/docs` 和 `/openapi.json` 为准。

## 环境要求

- Python 3.13 或更高版本
- [`uv`](https://docs.astral.sh/uv/)
- PostgreSQL
- Git 和可用的 C++17 编译器，用于构建独立的 RAG SDK
- Redis 可选；`REDIS_LAUNCH` 默认为 `false`

`translate-manager-rag` 从 [storyArk-rag-sdk](https://github.com/Miyamizu-MitsuhaSang/storyArk-rag-sdk) 的 `main` 分支安装；SDK 源码不包含在本仓库中。

## 配置

应用从仓库根目录读取 `env/.env.app` 和 `env/.env.db`。先创建这两个本地文件，并替换示例密码和密钥：

`env/.env.app`：

```dotenv
APP_NAME=translation-platform
API_PREFIX=/api/v1
LOG_LEVEL=INFO
AUTH_JWT_SECRET=replace-with-a-random-secret
AUTH_ACCESS_TOKEN_TTL_SECONDS=900
AUTH_REFRESH_TOKEN_TTL_DAYS=30
```

`env/.env.db`：

```dotenv
DB_USER=postgres
DB_PASSWORD=change-me
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=translation_platform
REDIS_LAUNCH=false
```

启动前需准备好 PostgreSQL 数据库及模型所需的数据表；仓库目前不包含数据库迁移脚本。启用 Redis 时，当前实现连接 `127.0.0.1:6379`。

不要把真实的数据库密码或 JWT 密钥提交到 Git。

## 本地运行

```bash
uv sync --locked
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

服务启动后可打开 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

## Docker

从仓库根目录构建并运行：

```bash
docker build -t storyark-translation-backend .
docker run --rm -p 8000:8000 \
  --env-file env/.env.app \
  --env-file env/.env.db \
  storyark-translation-backend
```

容器内的 `DB_HOST` 必须指向容器可访问的 PostgreSQL 地址；不要在连接宿主机数据库时使用容器自身的 `127.0.0.1`。
