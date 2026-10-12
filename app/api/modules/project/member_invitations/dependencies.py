from .....application.project.invitations.service import ProjectInvitationService

_service = ProjectInvitationService()


def get_project_invitation_service() -> ProjectInvitationService:
    """Return the shared project-member invitation application service."""
    return _service


__all__ = ["get_project_invitation_service"]
