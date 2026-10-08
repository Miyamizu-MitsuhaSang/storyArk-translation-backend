from tortoise import BaseDBAsyncClient


RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_by_id UUID NULL REFERENCES auth_users(id) ON DELETE SET NULL,
    name VARCHAR(160) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_format VARCHAR(16) NOT NULL DEFAULT 'unknown',
    mime_type VARCHAR(128) NULL,
    storage_uri VARCHAR(1024) NULL,
    file_size BIGINT NOT NULL DEFAULT 0,
    checksum_sha256 VARCHAR(64) NOT NULL,
    source_language VARCHAR(16) NOT NULL,
    target_language VARCHAR(16) NOT NULL,
    translation_memory_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(24) NOT NULL DEFAULT 'uploaded',
    version INT NOT NULL DEFAULT 1,
    segment_count INT NOT NULL DEFAULT 0,
    translated_segment_count INT NOT NULL DEFAULT 0,
    error_count INT NOT NULL DEFAULT 0,
    import_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_parse_job_id UUID NULL,
    parsed_at TIMESTAMPTZ NULL,
    archived_at TIMESTAMPTZ NULL,
    deleted_at TIMESTAMPTZ NULL,
    purge_after TIMESTAMPTZ NULL,
    purged_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_documents_file_size_nonnegative CHECK (file_size >= 0),
    CONSTRAINT ck_documents_counts_nonnegative CHECK (
        segment_count >= 0 AND translated_segment_count >= 0 AND error_count >= 0
    ),
    CONSTRAINT ck_documents_version_positive CHECK (version > 0)
);
CREATE INDEX IF NOT EXISTS idx_documents_project_status
    ON documents (project_id, status);
CREATE INDEX IF NOT EXISTS idx_documents_project_languages
    ON documents (project_id, source_language, target_language);
CREATE INDEX IF NOT EXISTS idx_documents_project_created
    ON documents (project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_documents_project_deleted
    ON documents (project_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_documents_purge_after
    ON documents (purge_after);

CREATE TABLE IF NOT EXISTS document_segments (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    segment_no INT NOT NULL,
    source_text TEXT NOT NULL,
    target_text TEXT NULL,
    source_language VARCHAR(16) NOT NULL,
    target_language VARCHAR(16) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'untranslated',
    workflow_state VARCHAR(24) NOT NULL DEFAULT 'draft',
    assigned_to_id UUID NULL REFERENCES auth_users(id) ON DELETE SET NULL,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
    version INT NOT NULL DEFAULT 1,
    translated_at TIMESTAMPTZ NULL,
    deleted_at TIMESTAMPTZ NULL,
    purge_after TIMESTAMPTZ NULL,
    CONSTRAINT uq_document_segments_document_no UNIQUE (document_id, segment_no),
    CONSTRAINT ck_document_segments_no_positive CHECK (segment_no > 0),
    CONSTRAINT ck_document_segments_version_positive CHECK (version > 0)
);
CREATE INDEX IF NOT EXISTS idx_document_segments_document_status
    ON document_segments (document_id, status);
CREATE INDEX IF NOT EXISTS idx_document_segments_document_workflow
    ON document_segments (document_id, workflow_state);
CREATE INDEX IF NOT EXISTS idx_document_segments_document_assigned
    ON document_segments (document_id, assigned_to_id);
CREATE INDEX IF NOT EXISTS idx_document_segments_document_deleted
    ON document_segments (document_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_document_segments_purge_after
    ON document_segments (purge_after);

CREATE TABLE IF NOT EXISTS segment_locks (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    segment_id UUID NOT NULL UNIQUE REFERENCES document_segments(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    lock_token VARCHAR(128) NOT NULL UNIQUE,
    locked_until TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS idx_segment_locks_locked_until
    ON segment_locks (locked_until);
CREATE INDEX IF NOT EXISTS idx_segment_locks_user_until
    ON segment_locks (user_id, locked_until);

"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP TABLE IF EXISTS segment_locks;
DROP TABLE IF EXISTS document_segments;
DROP TABLE IF EXISTS documents;
"""
