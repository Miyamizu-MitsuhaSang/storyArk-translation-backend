from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE translation_memory_libraries
    ADD COLUMN IF NOT EXISTS content_version INT NOT NULL DEFAULT 1;
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE translation_memory_libraries
    DROP COLUMN IF EXISTS content_version;
"""
