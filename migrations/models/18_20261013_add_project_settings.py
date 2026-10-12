from tortoise import BaseDBAsyncClient


RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
CREATE TABLE IF NOT EXISTS project_settings (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    project_id UUID NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    default_source_language VARCHAR(16) NULL,
    default_target_language VARCHAR(16) NULL,
    terminology_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    translation_memory_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    default_model VARCHAR(160) NULL,
    quality_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.700,
    revision INT NOT NULL DEFAULT 1,
    CONSTRAINT ck_project_settings_quality_threshold
        CHECK (quality_threshold >= 0 AND quality_threshold <= 1),
    CONSTRAINT ck_project_settings_revision CHECK (revision >= 1)
);
CREATE INDEX IF NOT EXISTS idx_project_settings_updated
    ON project_settings(project_id, updated_at);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP INDEX IF EXISTS idx_project_settings_updated;
DROP TABLE IF EXISTS project_settings;
"""
