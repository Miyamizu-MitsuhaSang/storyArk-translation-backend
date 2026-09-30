from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
CREATE TABLE IF NOT EXISTS translation_memory_imports (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    library_id UUID NOT NULL REFERENCES translation_memory_libraries(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    idempotency_key VARCHAR(160) NOT NULL,
    imported INT NOT NULL DEFAULT 0,
    skipped INT NOT NULL DEFAULT 0,
    invalid_rows JSONB NOT NULL DEFAULT '[]'::jsonb,
    CONSTRAINT uq_tm_import_idempotency UNIQUE (library_id, user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_tm_imports_library_created
    ON translation_memory_imports (library_id, created_at);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return "DROP TABLE IF EXISTS translation_memory_imports;"
