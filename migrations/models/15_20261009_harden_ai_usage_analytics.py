from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
CREATE TABLE IF NOT EXISTS ai_usage_records (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id UUID NULL,
    project_id UUID NULL,
    api_key_id UUID NULL,
    project_api_key_binding_id UUID NULL,
    provider VARCHAR(32) NOT NULL,
    model VARCHAR(120) NOT NULL,
    provider_request_id VARCHAR(255) NULL,
    status VARCHAR(16) NOT NULL,
    input_tokens BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    cached_input_tokens BIGINT NOT NULL DEFAULT 0,
    reasoning_tokens BIGINT NOT NULL DEFAULT 0,
    total_tokens BIGINT NOT NULL DEFAULT 0,
    cost NUMERIC(20,8) NOT NULL DEFAULT 0,
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    latency_ms INT NULL,
    error_code VARCHAR(80) NULL,
    CONSTRAINT ck_ai_usage_status CHECK (status IN ('succeeded','failed','timeout'))
);
ALTER TABLE ai_usage_records
    ADD CONSTRAINT ck_ai_usage_input_tokens_non_negative CHECK (input_tokens >= 0),
    ADD CONSTRAINT ck_ai_usage_output_tokens_non_negative CHECK (output_tokens >= 0),
    ADD CONSTRAINT ck_ai_usage_cached_input_tokens_non_negative CHECK (cached_input_tokens >= 0),
    ADD CONSTRAINT ck_ai_usage_reasoning_tokens_non_negative CHECK (reasoning_tokens >= 0),
    ADD CONSTRAINT ck_ai_usage_total_tokens_non_negative CHECK (total_tokens >= 0),
    ADD CONSTRAINT ck_ai_usage_cost_non_negative CHECK (cost >= 0),
    ADD CONSTRAINT ck_ai_usage_latency_non_negative CHECK (latency_ms IS NULL OR latency_ms >= 0);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_usage_provider_request
    ON ai_usage_records(provider, provider_request_id)
    WHERE provider_request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_usage_user_completed ON ai_usage_records(user_id, completed_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_project_completed ON ai_usage_records(project_id, completed_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_api_key_completed ON ai_usage_records(api_key_id, completed_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_provider_model_completed ON ai_usage_records(provider, model, completed_at);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP INDEX IF EXISTS uq_ai_usage_provider_request;
DROP INDEX IF EXISTS idx_ai_usage_user_completed;
DROP INDEX IF EXISTS idx_ai_usage_project_completed;
DROP INDEX IF EXISTS idx_ai_usage_api_key_completed;
DROP INDEX IF EXISTS idx_ai_usage_provider_model_completed;
ALTER TABLE ai_usage_records DROP CONSTRAINT IF EXISTS ck_ai_usage_input_tokens_non_negative;
ALTER TABLE ai_usage_records DROP CONSTRAINT IF EXISTS ck_ai_usage_output_tokens_non_negative;
ALTER TABLE ai_usage_records DROP CONSTRAINT IF EXISTS ck_ai_usage_cached_input_tokens_non_negative;
ALTER TABLE ai_usage_records DROP CONSTRAINT IF EXISTS ck_ai_usage_reasoning_tokens_non_negative;
ALTER TABLE ai_usage_records DROP CONSTRAINT IF EXISTS ck_ai_usage_total_tokens_non_negative;
ALTER TABLE ai_usage_records DROP CONSTRAINT IF EXISTS ck_ai_usage_cost_non_negative;
ALTER TABLE ai_usage_records DROP CONSTRAINT IF EXISTS ck_ai_usage_latency_non_negative;
"""
