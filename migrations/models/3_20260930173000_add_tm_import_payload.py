from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE translation_memory_imports ADD COLUMN IF NOT EXISTS rows JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE translation_memory_imports ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'queued';
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE translation_memory_imports DROP COLUMN IF EXISTS rows;
ALTER TABLE translation_memory_imports DROP COLUMN IF EXISTS status;
"""
