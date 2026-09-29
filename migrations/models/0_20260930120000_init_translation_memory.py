from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
CREATE TABLE IF NOT EXISTS translation_memory_libraries (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    scope VARCHAR(16) NOT NULL,
    owner_user_id UUID NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    name VARCHAR(160) NOT NULL,
    description TEXT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'active',
    content_version INT NOT NULL DEFAULT 1,
    CONSTRAINT ck_tm_library_scope_owner CHECK (
        (scope = 'platform' AND owner_user_id IS NULL)
        OR (scope = 'user' AND owner_user_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_tm_libraries_scope_status
    ON translation_memory_libraries (scope, status);
CREATE INDEX IF NOT EXISTS idx_tm_libraries_owner_status
    ON translation_memory_libraries (owner_user_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tm_one_active_user_library
    ON translation_memory_libraries (owner_user_id)
    WHERE scope = 'user' AND status = 'active';

CREATE TABLE IF NOT EXISTS translation_memory_entries (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    library_id UUID NOT NULL REFERENCES translation_memory_libraries(id) ON DELETE CASCADE,
    source_language VARCHAR(16) NOT NULL,
    target_language VARCHAR(16) NOT NULL,
    source_text TEXT NOT NULL,
    target_text TEXT NOT NULL,
    source_hash VARCHAR(128) NOT NULL,
    target_hash VARCHAR(128) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'active',
    origin VARCHAR(32) NOT NULL,
    revision INT NOT NULL DEFAULT 1,
    deleted_at TIMESTAMPTZ NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_tm_entry_dedupe UNIQUE
        (library_id, source_language, target_language, source_hash, target_hash)
);
CREATE INDEX IF NOT EXISTS idx_tm_entries_lookup
    ON translation_memory_entries (library_id, source_language, target_language, source_hash);
CREATE INDEX IF NOT EXISTS idx_tm_entries_status_updated
    ON translation_memory_entries (library_id, status, updated_at);

CREATE TABLE IF NOT EXISTS translation_memory_entry_revisions (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    entry_id UUID NOT NULL REFERENCES translation_memory_entries(id) ON DELETE CASCADE,
    version INT NOT NULL,
    snapshot JSONB NOT NULL,
    changed_by_id UUID NULL,
    project_id UUID NULL,
    document_id UUID NULL,
    segment_id UUID NULL,
    change_note TEXT NULL,
    CONSTRAINT uq_tm_entry_revision UNIQUE (entry_id, version)
);
CREATE INDEX IF NOT EXISTS idx_tm_revisions_entry_version
    ON translation_memory_entry_revisions (entry_id, version);
CREATE INDEX IF NOT EXISTS idx_tm_revisions_changed_by
    ON translation_memory_entry_revisions (changed_by_id);

CREATE TABLE IF NOT EXISTS translation_memory_entry_sources (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    entry_id UUID NOT NULL REFERENCES translation_memory_entries(id) ON DELETE CASCADE,
    provider VARCHAR(64) NULL,
    user_id UUID NULL,
    project_id UUID NULL,
    document_id UUID NULL,
    segment_id UUID NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_tm_sources_entry_project
    ON translation_memory_entry_sources (entry_id, project_id);
CREATE INDEX IF NOT EXISTS idx_tm_sources_project
    ON translation_memory_entry_sources (project_id);
CREATE INDEX IF NOT EXISTS idx_tm_sources_user
    ON translation_memory_entry_sources (user_id);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP TABLE IF EXISTS translation_memory_entry_sources;
DROP TABLE IF EXISTS translation_memory_entry_revisions;
DROP TABLE IF EXISTS translation_memory_entries;
DROP INDEX IF EXISTS uq_tm_one_active_user_library;
DROP TABLE IF EXISTS translation_memory_libraries;
"""
