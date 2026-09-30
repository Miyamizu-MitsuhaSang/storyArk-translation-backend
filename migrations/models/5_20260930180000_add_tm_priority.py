from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE translation_memory_libraries
    ADD COLUMN IF NOT EXISTS priority INT NOT NULL DEFAULT 0;
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE translation_memory_libraries
    DROP COLUMN IF EXISTS priority;
"""
