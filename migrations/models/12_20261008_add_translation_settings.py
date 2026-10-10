from tortoise import BaseDBAsyncClient


RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
CREATE TABLE IF NOT EXISTS translation_roles (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(160) NOT NULL,
    description TEXT NULL,
    detailed_injection TEXT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    revision INT NOT NULL DEFAULT 1 CHECK (revision >= 1),
    deleted_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_translation_roles_project_name UNIQUE (project_id, name)
);
CREATE INDEX IF NOT EXISTS idx_translation_roles_project_sort
    ON translation_roles (project_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_translation_roles_project_deleted
    ON translation_roles (project_id, deleted_at);

CREATE TABLE IF NOT EXISTS translation_rules (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type VARCHAR(16) NOT NULL CHECK (type IN ('general', 'category')),
    name VARCHAR(160) NOT NULL,
    text TEXT NOT NULL,
    category VARCHAR(80) NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    revision INT NOT NULL DEFAULT 1 CHECK (revision >= 1),
    deleted_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_translation_rules_project_name_category
        UNIQUE (project_id, type, name, category)
);
CREATE INDEX IF NOT EXISTS idx_translation_rules_project_type
    ON translation_rules (project_id, type);
CREATE INDEX IF NOT EXISTS idx_translation_rules_project_category
    ON translation_rules (project_id, category);
CREATE INDEX IF NOT EXISTS idx_translation_rules_project_deleted
    ON translation_rules (project_id, deleted_at);

CREATE TABLE IF NOT EXISTS culture_rules (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    language VARCHAR(16) NOT NULL,
    name VARCHAR(160) NOT NULL,
    text TEXT NOT NULL,
    category VARCHAR(80) NULL,
    revision INT NOT NULL DEFAULT 1 CHECK (revision >= 1),
    deleted_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_culture_rules_project_name_category
        UNIQUE (project_id, language, name, category)
);
CREATE INDEX IF NOT EXISTS idx_culture_rules_project_language
    ON culture_rules (project_id, language);
CREATE INDEX IF NOT EXISTS idx_culture_rules_project_deleted
    ON culture_rules (project_id, deleted_at);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP TABLE IF EXISTS culture_rules;
DROP TABLE IF EXISTS translation_rules;
DROP TABLE IF EXISTS translation_roles;
"""
