from tortoise import BaseDBAsyncClient


RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE translation_memory_entry_sources
    ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ NULL;

CREATE TABLE IF NOT EXISTS project_audit_events (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    project_id UUID NOT NULL,
    actor_user_id UUID NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id UUID NULL,
    action VARCHAR(96) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_project_audit_project_created
    ON project_audit_events (project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_project_audit_actor_created
    ON project_audit_events (project_id, actor_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_project_audit_resource_created
    ON project_audit_events (project_id, resource_type, created_at);
CREATE INDEX IF NOT EXISTS idx_project_audit_action_created
    ON project_audit_events (project_id, action, created_at);

CREATE TABLE IF NOT EXISTS api_idempotency_records (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id UUID NOT NULL,
    operation VARCHAR(96) NOT NULL,
    scope VARCHAR(160) NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    response_json JSONB NULL,
    CONSTRAINT uq_api_idempotency_user_key UNIQUE (user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_api_idempotency_scope_created
    ON api_idempotency_records (scope, created_at);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP TABLE IF EXISTS api_idempotency_records;
DROP TABLE IF EXISTS project_audit_events;
ALTER TABLE translation_memory_entry_sources DROP COLUMN IF EXISTS invalidated_at;
"""
