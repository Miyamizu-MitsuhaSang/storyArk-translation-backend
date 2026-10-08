from tortoise import BaseDBAsyncClient


RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE document_segments
    ADD COLUMN IF NOT EXISTS translator_note TEXT NULL;
ALTER TABLE document_segments
    ADD COLUMN IF NOT EXISTS qa_results JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE document_segments
    ADD COLUMN IF NOT EXISTS qa_checked_at TIMESTAMPTZ NULL;
ALTER TABLE document_segments
    ADD COLUMN IF NOT EXISTS change_history JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS segment_suggestions (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    segment_id UUID NOT NULL REFERENCES document_segments(id) ON DELETE CASCADE,
    source VARCHAR(32) NOT NULL,
    text TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider VARCHAR(64) NOT NULL DEFAULT 'internal',
    model VARCHAR(128) NULL,
    context_version VARCHAR(128) NULL,
    latency_ms INT NULL
);
CREATE INDEX IF NOT EXISTS idx_segment_suggestions_segment_created
    ON segment_suggestions (segment_id, created_at);
CREATE INDEX IF NOT EXISTS idx_segment_suggestions_source_created
    ON segment_suggestions (source, created_at);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP TABLE IF EXISTS segment_suggestions;
ALTER TABLE document_segments DROP COLUMN IF EXISTS change_history;
ALTER TABLE document_segments DROP COLUMN IF EXISTS qa_checked_at;
ALTER TABLE document_segments DROP COLUMN IF EXISTS qa_results;
ALTER TABLE document_segments DROP COLUMN IF EXISTS translator_note;
"""
