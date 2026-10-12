from tortoise import BaseDBAsyncClient


RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
ALTER TABLE project_invitations
    ADD COLUMN IF NOT EXISTS invite_code_id UUID NULL;
ALTER TABLE project_invitations
    ADD CONSTRAINT fk_project_invitations_invite_code
    FOREIGN KEY (invite_code_id) REFERENCES project_invite_codes(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_project_invitations_invite_code
    ON project_invitations (invite_code_id);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
DROP INDEX IF EXISTS idx_project_invitations_invite_code;
ALTER TABLE project_invitations DROP CONSTRAINT IF EXISTS fk_project_invitations_invite_code;
ALTER TABLE project_invitations DROP COLUMN IF EXISTS invite_code_id;
"""
