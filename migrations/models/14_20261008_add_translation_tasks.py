from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
CREATE TABLE IF NOT EXISTS translation_tasks (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_by_id UUID NULL REFERENCES auth_users(id) ON DELETE SET NULL,
    name VARCHAR(160) NOT NULL,
    source_language VARCHAR(16) NOT NULL,
    target_languages JSONB NOT NULL DEFAULT '[]'::jsonb,
    version_id UUID NULL,
    api_key_id UUID NULL,
    api_key_provider VARCHAR(32) NULL,
    api_key_label VARCHAR(120) NULL,
    api_key_masked VARCHAR(128) NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    progress INT NOT NULL DEFAULT 0,
    error_code VARCHAR(64) NULL,
    error_message VARCHAR(512) NULL,
    result JSONB NULL,
    CONSTRAINT ck_translation_tasks_progress CHECK (progress >= 0 AND progress <= 100),
    CONSTRAINT ck_translation_tasks_status CHECK (status IN ('queued','translating','review','completed','failed','cancelled'))
);
CREATE INDEX IF NOT EXISTS idx_translation_tasks_project_created ON translation_tasks(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_translation_tasks_project_status ON translation_tasks(project_id, status);
CREATE INDEX IF NOT EXISTS idx_translation_tasks_api_key_status ON translation_tasks(api_key_id, status);

CREATE TABLE IF NOT EXISTS translation_task_files (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    task_id UUID NOT NULL REFERENCES translation_tasks(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    CONSTRAINT uq_translation_task_files_task_document UNIQUE (task_id, document_id)
);
CREATE INDEX IF NOT EXISTS idx_translation_task_files_task ON translation_task_files(task_id);
CREATE INDEX IF NOT EXISTS idx_translation_task_files_document ON translation_task_files(document_id);
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS model_type VARCHAR(64);
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS model VARCHAR(128);
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS source_column VARCHAR(128);
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS target_columns JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS sheet_names JSONB;
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS overwrite BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS job_id UUID;
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS output_storage_key VARCHAR(1024);
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS output_file_name VARCHAR(255);
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS output_size_bytes BIGINT;
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS completed_cells INT NOT NULL DEFAULT 0;
ALTER TABLE translation_tasks ADD COLUMN IF NOT EXISTS total_cells INT NOT NULL DEFAULT 0;
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP TABLE IF EXISTS translation_task_files;
DROP TABLE IF EXISTS translation_tasks;
"""
