from tortoise import BaseDBAsyncClient


RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE auth_user_preferences
    ADD COLUMN IF NOT EXISTS allow_member_search BOOLEAN NOT NULL DEFAULT FALSE;
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE auth_user_preferences DROP COLUMN IF EXISTS allow_member_search;
"""
