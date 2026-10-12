from tortoise import BaseDBAsyncClient


RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE ai_usage_records
    ADD COLUMN IF NOT EXISTS pricing_version VARCHAR(64) NULL;
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE ai_usage_records DROP COLUMN IF EXISTS pricing_version;
"""
