"""Project business versions and their document membership."""

from tortoise import fields

from .base import TimestampedModel


class ProjectVersion(TimestampedModel):
    """A named project work batch, not a content-history snapshot."""

    project = fields.ForeignKeyField(
        "models.Project",
        related_name="versions",
        on_delete=fields.CASCADE,
        description="业务版本所属项目；项目删除时一并删除版本。",
    )
    version_number = fields.IntField(description="项目内由系统分配且不可变的整数版本编号。")
    name: str | None = fields.CharField(
        max_length=160,
        null=True,
        description="用户自定义展示名称；允许为空和重复。",
    )
    description: str | None = fields.TextField(null=True, description="版本用途或交付说明。")
    source_language: str | None = fields.CharField(
        max_length=16,
        null=True,
        description="该版本的源语言配置；为空表示沿用项目配置。",
    )
    target_languages: list[str] = fields.JSONField(
        default=list,
        description="该版本的目标语言配置；为空列表表示沿用项目配置。",
    )
    created_by = fields.ForeignKeyField(
        "models.User",
        related_name="created_project_versions",
        null=True,
        on_delete=fields.SET_NULL,
        description="版本创建人；用户删除后保留版本并清空此关联。",
    )

    class Meta:
        table = "project_versions"
        unique_together = (("project", "version_number"),)
        indexes = [
            ("project_id", "version_number"),
            ("project_id", "created_at"),
            ("project_id", "name"),
        ]
