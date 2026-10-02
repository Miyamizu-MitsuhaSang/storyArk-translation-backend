from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
CREATE TABLE IF NOT EXISTS background_jobs (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    type VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    resource_type VARCHAR(64) NOT NULL,
    resource_id UUID NOT NULL,
    requested_version INT NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    worker_id VARCHAR(128) NULL,
    lease_expires_at TIMESTAMPTZ NULL,
    result JSONB NULL,
    error_code VARCHAR(64) NULL,
    error_message VARCHAR(512) NULL,
    CONSTRAINT ck_background_jobs_attempts CHECK (attempts >= 0 AND max_attempts > 0)
);
CREATE INDEX IF NOT EXISTS idx_background_jobs_status_available
    ON background_jobs (status, available_at);
CREATE INDEX IF NOT EXISTS idx_background_jobs_resource_version
    ON background_jobs (resource_type, resource_id, requested_version);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return "DROP TABLE IF EXISTS background_jobs;"
