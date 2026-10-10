from tortoise import BaseDBAsyncClient


RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS next_version_number INT NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS project_versions (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_number INT NOT NULL,
    name VARCHAR(160) NULL,
    description TEXT NULL,
    source_language VARCHAR(16) NULL,
    target_languages JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by_id UUID NULL REFERENCES auth_users(id) ON DELETE SET NULL,
    CONSTRAINT uq_project_versions_project_number UNIQUE (project_id, version_number),
    CONSTRAINT ck_project_versions_number_positive CHECK (version_number > 0)
);
CREATE INDEX IF NOT EXISTS idx_project_versions_project_number
    ON project_versions (project_id, version_number);
CREATE INDEX IF NOT EXISTS idx_project_versions_project_created
    ON project_versions (project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_project_versions_project_name
    ON project_versions (project_id, name);

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS version_id UUID NULL REFERENCES project_versions(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_documents_project_version
    ON documents (project_id, version_id);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP INDEX IF EXISTS idx_documents_project_version;
ALTER TABLE documents DROP COLUMN IF EXISTS version_id;
DROP TABLE IF EXISTS project_versions;
ALTER TABLE projects DROP COLUMN IF EXISTS next_version_number;
"""
