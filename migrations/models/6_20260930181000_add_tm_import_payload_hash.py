from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE translation_memory_imports
    ADD COLUMN IF NOT EXISTS payload_hash VARCHAR(64) NOT NULL DEFAULT '';
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE translation_memory_imports
    DROP COLUMN IF EXISTS payload_hash;
"""
