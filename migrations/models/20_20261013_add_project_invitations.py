from tortoise import BaseDBAsyncClient


RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
CREATE TABLE IF NOT EXISTS project_invitations (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    invited_by_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    target_user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    role VARCHAR(24) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ NULL,
    declined_at TIMESTAMPTZ NULL,
    revoked_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_project_invitation_status CHECK (status IN ('pending', 'accepted', 'declined', 'revoked', 'expired'))
);
CREATE INDEX IF NOT EXISTS idx_project_invitations_project_status
    ON project_invitations (project_id, status);
CREATE INDEX IF NOT EXISTS idx_project_invitations_target_status
    ON project_invitations (target_user_id, status);
CREATE INDEX IF NOT EXISTS idx_project_invitations_expires_at
    ON project_invitations (expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_invitation_pending_target
    ON project_invitations (project_id, target_user_id)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS project_invite_codes (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_by_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    role VARCHAR(24) NOT NULL,
    code_hash VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    expires_at TIMESTAMPTZ NOT NULL,
    max_uses INT NOT NULL DEFAULT 1,
    used_count INT NOT NULL DEFAULT 0,
    revoked_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_project_invite_code_status CHECK (status IN ('active', 'revoked', 'expired', 'exhausted')),
    CONSTRAINT ck_project_invite_code_uses CHECK (max_uses >= 1 AND used_count >= 0 AND used_count <= max_uses)
);
CREATE INDEX IF NOT EXISTS idx_project_invite_codes_project_status
    ON project_invite_codes (project_id, status);
CREATE INDEX IF NOT EXISTS idx_project_invite_codes_expires_at
    ON project_invite_codes (expires_at);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP TABLE IF EXISTS project_invite_codes;
DROP TABLE IF EXISTS project_invitations;
"""
