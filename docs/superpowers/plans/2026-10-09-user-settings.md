# 用户设置分域 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为账户外观、界面语言和现有项目设置建立可扩展的分域模型、API、前端同步和文档契约。

**Architecture:** 用户设置拆为 `AppearanceSettings` 和 `UserPreferences` 两张用户级表，通过 `/api/v1/auth/me/settings` 聚合读取和部分更新；项目设置继续使用项目级模型、服务和路由。后端负责事实来源、校验、权限和迁移，前端负责状态加载、界面语言文案和主题呈现。

**Tech Stack:** FastAPI、Tortoise ORM、Pydantic、PostgreSQL、现有认证依赖、React/TypeScript、Vitest/pytest、API contract 文档。

**Spec:** `docs/superpowers/specs/2026-10-09-user-settings-design.md`

## Global Constraints

- `locale` 只表示网站界面语言，不表示翻译任务源语言或目标语言。
- `AppearanceSettings`、`UserPreferences`、`ProjectSettings` 保持独立作用域，不使用混合 JSON settings 表。
- 用户设置必须通过当前登录用户隔离；请求体不得接收可篡改的 `user_id`。
- PATCH 只更新出现的字段；新增字段必须有类型、校验、迁移、文档和测试。
- 保留工作区现有未提交改动，不执行 reset、clean 或覆盖无关文件。
- 所有 API 字段和路由 description 使用中文，并同步 API 契约源及后端副本。

## 文件与边界

- `app/models/user_settings.py`：用户设置 ORM 模型，仅定义表结构和字段描述。
- `app/models/auth.py`、`app/models/__init__.py`：建立用户反向关系并导出模型。
- `app/application/auth/settings/schemas.py`：设置请求/响应 schema、枚举和默认值。
- `app/application/auth/settings/service.py`：默认值、读取、部分更新、revision 和用户隔离业务规则。
- `app/api/modules/auth/settings/routes.py`：当前用户设置 GET/PATCH 路由和 OpenAPI description。
- `app/api/modules/auth/routes.py`、`app/api/router.py`：挂载 settings 子路由，保持 `/api/v1/auth` 前缀。
- `migrations/models/<next>_add_user_settings.py`：新增两张表和约束；使用仓库实际下一个迁移序号。
- `tests/test_user_settings_service.py`、`tests/test_user_settings_api.py`：服务和 API 回归测试。
- `api-contract/docs/api.md`、`docs/api.md`：API 契约源和同步副本。
- `../storyark_frontend/src/api/auth.ts`：用户设置 API 客户端。
- `../storyark_frontend/src/domain/types.ts`：主题三态、界面 locale 和响应类型。
- `../storyark_frontend/src/data/remoteAdapter.ts`：读取/更新用户设置，缓存只作启动优化。
- `../storyark_frontend/src/components/TopBar.tsx`：主题切换接入 `system` 语义。
- `../storyark_frontend/src/App.tsx` 或现有会话状态入口：登录后加载设置并提供给页面。
- `../storyark_frontend/src/i18n/*`：界面文案资源和 locale 选择器；实现前先确认当前 i18n 组织方式。
- `../storyark_frontend/src/**/*.test.*`：主题、界面语言、刷新和未知字段兼容测试。

## 第一阶段：后端模型与迁移

### Task 1: 添加用户设置模型

**Files:**
- Create: `app/models/user_settings.py`
- Modify: `app/models/auth.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_user_settings_service.py`

**Interfaces:**
- Produces `AppearanceSettings(user, theme, revision)` and `UserPreferences(user, locale, revision)` ORM models with one-to-one `user_id` constraints.

- [ ] **Step 1: 写模型约束测试**

```python
async def test_user_settings_are_unique_per_user(db):
    user = await User.create(username="u", email="u@example.com", password_hash="x", display_name="U")
    await AppearanceSettings.create(user=user, theme="system")
    with pytest.raises(IntegrityError):
        await AppearanceSettings.create(user=user, theme="dark")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_user_settings_service.py::test_user_settings_are_unique_per_user -q`
Expected: FAIL because the models do not exist.

- [ ] **Step 3: 实现模型**

使用统一 `TimestampedModel`、UUID 主键、`ForeignKeyField("models.User", on_delete=CASCADE)`、`theme`/`locale` 字段、`revision` 字段和 `Meta.table`。所有字段添加中文 `description`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_user_settings_service.py::test_user_settings_are_unique_per_user -q`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add app/models/user_settings.py app/models/auth.py app/models/__init__.py tests/test_user_settings_service.py
git commit -m "feat: add user settings models"
```

### Task 2: 创建数据库迁移

**Files:**
- Create: `migrations/models/<next>_add_user_settings.py`
- Test: `tests/test_user_settings_service.py`

**Interfaces:**
- Produces PostgreSQL tables `auth_appearance_settings` and `auth_user_preferences`, unique `user_id` constraints, foreign keys and indexes.

- [ ] **Step 1: 写迁移结构测试**

```python
async def test_user_settings_tables_exist(db):
    tables = await fetch_table_names(db)
    assert {"auth_appearance_settings", "auth_user_preferences"} <= tables
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_user_settings_service.py::test_user_settings_tables_exist -q`
Expected: FAIL because the migration has not been applied.

- [ ] **Step 3: 编写迁移**

从当前 `migrations/models` 的最高序号确定 `<next>`，为两张表创建字段、约束和索引；不要修改或重排已有迁移。

- [ ] **Step 4: 应用并验证迁移**

Run: `uv run aerich -c aerich.ini upgrade && uv run pytest tests/test_user_settings_service.py::test_user_settings_tables_exist -q`
Expected: migration succeeds and test passes.

- [ ] **Step 5: 提交**

```bash
git add migrations/models/<next>_add_user_settings.py
git commit -m "feat: migrate user settings tables"
```

## 第二阶段：后端业务与 API

### Task 3: 定义 settings schema 和服务

**Files:**
- Create: `app/application/auth/settings/__init__.py`
- Create: `app/application/auth/settings/schemas.py`
- Create: `app/application/auth/settings/service.py`
- Test: `tests/test_user_settings_service.py`

**Interfaces:**
- `GET` service: `async def get(user: User) -> UserSettingsResponse`
- `PATCH` service: `async def update(user: User, request: UserSettingsUpdateRequest) -> UserSettingsResponse`
- `Theme = Literal["light", "dark", "system"]`
- `UserSettingsResponse` groups `appearance` and `preferences`.

- [ ] **Step 1: 写服务失败测试**

```python
async def test_get_creates_defaults(user):
    result = await UserSettingsService().get(user)
    assert result.appearance.theme == "system"
    assert result.preferences.locale == "zh-CN"

async def test_patch_updates_only_provided_group(user):
    result = await UserSettingsService().update(user, UserSettingsUpdateRequest(preferences={"locale": "en-US"}))
    assert result.preferences.locale == "en-US"
    assert result.appearance.theme == "system"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_user_settings_service.py -q`
Expected: FAIL because schemas and service are missing.

- [ ] **Step 3: 实现最小服务**

集中声明默认值和 locale 白名单；首次读取使用事务创建两条记录；PATCH 使用 `exclude_unset=True`，逐组更新并递增对应 revision；不接受 user id；将 `IntegrityError` 转为现有结构化业务错误。

- [ ] **Step 4: 补充边界测试并运行**

覆盖非法 theme、非法 locale、空 PATCH、revision 冲突、两个用户互不可见和重复并发创建。Run: `uv run pytest tests/test_user_settings_service.py -q`，Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/application/auth/settings tests/test_user_settings_service.py
git commit -m "feat: add user settings service"
```

### Task 4: 添加认证路由并挂载

**Files:**
- Create: `app/api/modules/auth/settings/__init__.py`
- Create: `app/api/modules/auth/settings/routes.py`
- Modify: `app/api/modules/auth/routes.py`
- Modify: `app/api/router.py`
- Test: `tests/test_user_settings_api.py`

**Interfaces:**
- `GET /api/v1/auth/me/settings`
- `PATCH /api/v1/auth/me/settings`

- [ ] **Step 1: 写 API 失败测试**

```python
async def test_get_settings_requires_auth(client):
    response = await client.get("/api/v1/auth/me/settings")
    assert response.status_code == 401

async def test_patch_settings_returns_grouped_response(auth_client):
    response = await auth_client.patch("/api/v1/auth/me/settings", json={"appearance": {"theme": "dark"}})
    assert response.status_code == 200
    assert response.json()["appearance"]["theme"] == "dark"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_user_settings_api.py -q`
Expected: FAIL with 404 until routes are mounted.

- [ ] **Step 3: 实现路由**

使用现有 `get_current_user` 依赖和应用服务；为每个路由填写中文 `summary`/`description`，描述默认值、部分更新、权限和 locale 语义；不在路由中写数据库逻辑。

- [ ] **Step 4: 运行 API 与 OpenAPI 测试**

Run: `uv run pytest tests/test_user_settings_api.py -q`；检查 `/openapi.json` 中两个路径和 description 存在。Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/api/modules/auth/settings app/api/modules/auth/routes.py app/api/router.py tests/test_user_settings_api.py
git commit -m "feat: expose user settings api"
```

## 第三阶段：API 文档与数据库文档

### Task 5: 同步 API 契约和数据库说明

**Files:**
- Modify: `api-contract/docs/api.md`
- Modify: `docs/api.md`
- Modify: `docs/database.md`
- Test: `tests/test_user_settings_api.py`

- [ ] **Step 1: 在契约源加入两个接口**

写明请求/响应 JSON、字段 description、默认值、错误码、认证要求、PATCH 部分更新语义和 locale 仅表示界面语言。

- [ ] **Step 2: 加入数据库表说明**

记录两张表字段、唯一约束、外键级联策略、revision 用途和未来扩展规则；注明项目设置仍是独立作用域。

- [ ] **Step 3: 同步后端文档副本**

按仓库既有同步脚本执行，确认 `docs/api.md` 与契约源内容一致。

- [ ] **Step 4: 验证文档和 OpenAPI 一致**

Run: `./scripts/check-api-docs.sh`（若存在）以及 `uv run pytest tests/test_user_settings_api.py -q`。Expected: PASS；若脚本路径不同，使用仓库当前文档校验命令。

- [ ] **Step 5: 提交**

```bash
git add api-contract/docs/api.md docs/api.md docs/database.md
git commit -m "docs: document user settings contract"
```

## 第四阶段：前端接入

### Task 6: 类型、API 客户端和启动加载

**Files:**
- Modify: `../storyark_frontend/src/domain/types.ts`
- Modify: `../storyark_frontend/src/api/auth.ts`
- Modify: `../storyark_frontend/src/data/remoteAdapter.ts`
- Modify: `../storyark_frontend/src/App.tsx` 或现有会话入口
- Test: `../storyark_frontend/src/**/*.test.*`

**Interfaces:**
- `Theme = "light" | "dark" | "system"`
- `UserSettingsResponse` 与后端分组字段一致。
- `getUserSettings()` 和 `patchUserSettings(input)` API 客户端函数。

- [ ] **Step 1: 写客户端失败测试**

验证登录后调用 GET、PATCH 发送仅变化字段、响应未知字段不会导致解析崩溃。

- [ ] **Step 2: 运行前端测试确认失败**

Run: `npm test -- --run`（使用前端仓库现有命令）。Expected: FAIL because the client methods/types are missing.

- [ ] **Step 3: 实现类型和 API 客户端**

将 `system` 加入 Theme；把设置 API 放入认证客户端；localStorage 只缓存最近成功响应，不覆盖服务器字段。

- [ ] **Step 4: 接入会话启动加载**

登录成功或恢复会话后加载设置；登出时清理内存中的用户设置；请求失败时保留默认值并显示现有错误提示机制。

- [ ] **Step 5: 运行测试并提交**

Run: `npm test -- --run`，Expected: PASS。

```bash
git add ../storyark_frontend/src/domain/types.ts ../storyark_frontend/src/api/auth.ts ../storyark_frontend/src/data/remoteAdapter.ts ../storyark_frontend/src/App.tsx
git commit -m "feat: load user settings in frontend"
```

### Task 7: 主题三态和界面语言 UI

**Files:**
- Modify: `../storyark_frontend/src/components/TopBar.tsx`
- Modify: `../storyark_frontend/src/pages/AccountPage.tsx` 或账户设置页面
- Modify: `../storyark_frontend/src/i18n/*`（按实际结构）
- Test: `../storyark_frontend/src/**/*.test.*`

- [ ] **Step 1: 写交互测试**

覆盖 `light`、`dark`、`system` 三态，`system` 监听 `prefers-color-scheme`，切换 locale 后页面文案刷新，刷新页面后从后端设置恢复。

- [ ] **Step 2: 实现主题解析**

显式主题直接应用；`system` 根据 `matchMedia` 应用并监听 change；每次用户操作调用 PATCH，失败时恢复上一次成功状态。

- [ ] **Step 3: 实现界面语言选择**

只切换 UI 文案资源，不修改项目源语言、目标语言、TM 语言或任务字段。

- [ ] **Step 4: 运行前端测试**

Run: `npm test -- --run`，Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add ../storyark_frontend/src/components/TopBar.tsx ../storyark_frontend/src/pages/AccountPage.tsx ../storyark_frontend/src/i18n
git commit -m "feat: support theme and interface locale settings"
```

## 第五阶段：联调、回归与发布检查

### Task 8: 全链路验证

**Files:**
- Modify only if verification finds a contract mismatch.
- Test: `tests/test_user_settings_service.py`, `tests/test_user_settings_api.py`, frontend tests, API docs checks.

- [ ] **Step 1: 执行后端 focused tests**

Run: `uv run pytest tests/test_user_settings_service.py tests/test_user_settings_api.py -q`，Expected: PASS。

- [ ] **Step 2: 执行既有 auth/project 回归**

Run: `uv run pytest tests/test_auth* tests/test_translation_settings_api.py -q`，Expected: PASS；记录与本变更无关的既有失败。

- [ ] **Step 3: 执行前端测试和构建**

Run: `npm test -- --run && npm run build`，Expected: PASS。

- [ ] **Step 4: 验证跨设备语义**

使用同一账户在两个会话分别修改 theme/locale，确认第二个会话重新读取后得到服务器值；确认项目设置接口仍按项目权限工作。

- [ ] **Step 5: 检查迁移和文档**

确认迁移从干净数据库可执行、重复升级无变化、OpenAPI 与 `api-contract/docs/api.md` 的路径和字段一致。

- [ ] **Step 6: 提交联调修正**

```bash
git add app api-contract docs ../storyark_frontend/src
git commit -m "test: verify user settings end to end"
```

## 覆盖检查

- AppearanceSettings 的独立表、默认值、三态主题、PATCH 和前端应用：Task 1-4、6-7。
- UserPreferences 的独立表、界面 locale 语义、白名单和跨设备加载：Task 1-7。
- ProjectSettings 保持独立且无回归：Task 5、8。
- 新字段必须通过显式列/schema/迁移/API 文档/测试扩展：Global Constraints、Task 1-5。
- 前后端职责边界：Spec 第 5 节、Task 3-4 与 Task 6-7。
