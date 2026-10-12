from tortoise import BaseDBAsyncClient


RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
CREATE TABLE IF NOT EXISTS auth_appearance_settings (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id UUID NOT NULL UNIQUE REFERENCES auth_users(id) ON DELETE CASCADE,
    theme VARCHAR(16) NOT NULL DEFAULT 'system',
    revision INT NOT NULL DEFAULT 1,
    CONSTRAINT ck_auth_appearance_theme CHECK (theme IN ('light', 'dark', 'system')),
    CONSTRAINT ck_auth_appearance_revision CHECK (revision >= 1)
);
CREATE INDEX IF NOT EXISTS idx_auth_appearance_updated ON auth_appearance_settings(user_id, updated_at);

CREATE TABLE IF NOT EXISTS auth_user_preferences (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id UUID NOT NULL UNIQUE REFERENCES auth_users(id) ON DELETE CASCADE,
    locale VARCHAR(35) NOT NULL DEFAULT 'zh-CN',
    revision INT NOT NULL DEFAULT 1,
    CONSTRAINT ck_auth_preferences_revision CHECK (revision >= 1)
);
CREATE INDEX IF NOT EXISTS idx_auth_preferences_updated ON auth_user_preferences(user_id, updated_at);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP TABLE IF EXISTS auth_user_preferences;
DROP TABLE IF EXISTS auth_appearance_settings;
"""
