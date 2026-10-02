from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
CREATE TABLE IF NOT EXISTS translation_memory_index_artifacts (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    library_id UUID NOT NULL REFERENCES translation_memory_libraries(id) ON DELETE CASCADE,
    content_version INT NOT NULL,
    format_version INT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'building',
    storage_uri VARCHAR(512) NULL,
    checksum VARCHAR(64) NULL,
    vectorizer_version VARCHAR(64) NOT NULL,
    row_count INT NOT NULL DEFAULT 0,
    feature_count INT NOT NULL DEFAULT 0,
    build_job_id UUID NULL REFERENCES background_jobs(id) ON DELETE SET NULL,
    built_at TIMESTAMPTZ NULL,
    activated_at TIMESTAMPTZ NULL,
    failure_reason VARCHAR(512) NULL,
    CONSTRAINT uq_tm_artifact_library_content_format UNIQUE (library_id, content_version, format_version)
);
CREATE INDEX IF NOT EXISTS idx_tm_artifacts_library_status
    ON translation_memory_index_artifacts (library_id, status);
CREATE INDEX IF NOT EXISTS idx_tm_artifacts_status_built
    ON translation_memory_index_artifacts (status, built_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tm_one_active_artifact
    ON translation_memory_index_artifacts (library_id)
    WHERE status = 'active';
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return "DROP TABLE IF EXISTS translation_memory_index_artifacts;"
