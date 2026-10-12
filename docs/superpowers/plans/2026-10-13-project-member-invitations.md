# Project Member Invitations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现仅面向已注册用户的项目成员搜索、定向邀请、一次性邀请码兑换和用户级可搜索隐私设置。

**Architecture:** 用户搜索候选由 `ProjectService` 查询 active 且 `UserPreferences.allow_member_search=true` 的用户；邀请和邀请码由 `ProjectInvitationService` 在 application 层编排，数据库模型保存哈希 token、状态和有效期。只有接受邀请或兑换邀请码的事务成功后才创建 `ProjectMember`；Redis 不作为邀请状态事实来源。

**Tech Stack:** FastAPI、Pydantic v2、Tortoise ORM、PostgreSQL/SQLite、pytest、Aerich migration。

**Spec:** `api-contract/docs/api.md` 成员邀请和用户设置设计，`src/storyark_frontend/docs/frontend-design.md` 成员管理页面设计。

## Global Constraints

- 只允许已注册且已登录用户加入项目；邀请码不能注册账户。
- `allow_member_search` 默认关闭，只影响候选搜索，不影响定向邀请接受或邀请码兑换。
- 邀请 token 只保存哈希；邀请码明文只在创建响应中返回一次。
- 项目不可见、邀请不可见和邀请码无效不得泄露其他用户或项目存在性。
- 项目成员创建必须在接受/兑换事务内完成，并防止重复成员和重复兑换。
- API 路由只做 HTTP 参数和错误映射，业务规则放在 `app/application`。

### Task 1: 用户可搜索设置

**Files:** `app/models/user_settings.py`, `app/application/auth/settings/schemas.py`, `app/application/auth/settings/service.py`, migration, `tests/test_user_settings_service.py`, `tests/test_user_settings_api.py`

- [ ] 写默认值、读写和 revision 冲突测试。
- [ ] 增加 `allow_member_search: bool = False` 并完成 ORM、schema、service 更新。
- [ ] 生成迁移并运行设置专项测试。

### Task 2: 邀请与邀请码模型和 application service

**Files:** `app/models/project_invitations.py`, `app/models/__init__.py`, `app/application/project/invitations/schemas.py`, `service.py`, `dependencies.py`, migration, `tests/test_project_invitations_service.py`

- [ ] 写候选搜索、定向邀请、接受/拒绝、邀请码生成/兑换、过期/撤销/重复成员测试。
- [ ] 实现哈希 token、状态校验、事务内创建成员和稳定错误码。
- [ ] 增加项目候选搜索和邀请查询所需 repository/application 查询。

### Task 3: API routes and OpenAPI

**Files:** `app/api/modules/project/member_invitations/routes.py`, `app/api/modules/project/routes.py`, `app/api/modules/auth/routes.py`, router dependencies, tests

- [ ] 注册项目候选、邀请、邀请码和当前用户邀请接口。
- [ ] 将 `Idempotency-Key` 接入接受邀请和邀请码兑换。
- [ ] 增加统一异常处理和 OpenAPI description。

### Task 4: Documentation and verification

- [ ] 同步 API 文档和前端设计文档。
- [ ] 运行 API 文档检查、专项测试、全量 pytest、compileall 和 diff check。
