from __future__ import annotations

from datetime import datetime

from tortoise import fields

from .base import TimestampedModel

INVITATION_STATUSES = ("pending", "accepted", "declined", "revoked", "expired")
INVITE_CODE_STATUSES = ("active", "revoked", "expired", "exhausted")


class ProjectInvitation(TimestampedModel):
    project = fields.ForeignKeyField("models.Project", related_name="invitations", on_delete=fields.CASCADE)
    invited_by = fields.ForeignKeyField("models.User", related_name="sent_project_invitations", on_delete=fields.CASCADE)
    target_user = fields.ForeignKeyField("models.User", related_name="received_project_invitations", on_delete=fields.CASCADE)
    invite_code = fields.ForeignKeyField(
        "models.ProjectInviteCode",
        related_name="invitations",
        null=True,
        on_delete=fields.SET_NULL,
        description="可选的邀请码来源；直接定向邀请为空。",
    )
    role = fields.CharField(max_length=24, description="接受后授予的项目角色。")
    status = fields.CharField(max_length=16, default="pending", choices=INVITATION_STATUSES)
    expires_at: datetime = fields.DatetimeField(description="邀请过期时间。")
    accepted_at: datetime | None = fields.DatetimeField(null=True)
    declined_at: datetime | None = fields.DatetimeField(null=True)
    revoked_at: datetime | None = fields.DatetimeField(null=True)

    class Meta:
        table = "project_invitations"
        indexes = [("project_id", "status"), ("target_user_id", "status"), ("expires_at",)]


class ProjectInviteCode(TimestampedModel):
    project = fields.ForeignKeyField("models.Project", related_name="invite_codes", on_delete=fields.CASCADE)
    created_by = fields.ForeignKeyField("models.User", related_name="created_project_invite_codes", on_delete=fields.CASCADE)
    role = fields.CharField(max_length=24)
    code_hash = fields.CharField(max_length=64, unique=True, db_index=True)
    status = fields.CharField(max_length=16, default="active", choices=INVITE_CODE_STATUSES)
    expires_at: datetime = fields.DatetimeField()
    max_uses = fields.IntField(default=1)
    used_count = fields.IntField(default=0)
    revoked_at: datetime | None = fields.DatetimeField(null=True)

    class Meta:
        table = "project_invite_codes"
        indexes = [("project_id", "status"), ("expires_at",)]


__all__ = ["INVITATION_STATUSES", "INVITE_CODE_STATUSES", "ProjectInvitation", "ProjectInviteCode"]
