from fastapi import APIRouter, Depends

from .....application.auth.settings.schemas import UserSettingsResponse, UserSettingsUpdateRequest
from .....application.auth.settings.service import UserSettingsService
from .....application.auth.schemas import ErrorResponse
from .....api.shared.dependencies import get_current_user
from .....models import User


user_settings_router = APIRouter(prefix="/me/settings", tags=["auth-settings"])


def get_user_settings_service() -> UserSettingsService:
    return UserSettingsService()


@user_settings_router.get(
    "",
    response_model=UserSettingsResponse,
    responses={401: {"model": ErrorResponse, "description": "需要登录"}},
    summary="读取当前用户设置",
    description="读取当前登录用户的外观、网站界面语言和成员搜索隐私设置。首次读取时使用默认值；locale 只表示界面语言，不表示翻译任务的源语言或目标语言。",
)
async def get_user_settings(
    user: User = Depends(get_current_user),
    service: UserSettingsService = Depends(get_user_settings_service),
) -> UserSettingsResponse:
    return await service.get(user)


@user_settings_router.patch(
    "",
    response_model=UserSettingsResponse,
    responses={
        401: {"model": ErrorResponse, "description": "需要登录"},
        409: {"model": ErrorResponse, "description": "设置版本冲突"},
        422: {"model": ErrorResponse, "description": "设置字段无效"},
    },
    summary="部分更新当前用户设置",
    description="部分更新外观、网站界面语言或成员搜索隐私设置。只更新请求中出现的字段，可使用 revision 进行并发控制；项目级翻译设置不通过此接口修改。",
)
async def update_user_settings(
    request: UserSettingsUpdateRequest,
    user: User = Depends(get_current_user),
    service: UserSettingsService = Depends(get_user_settings_service),
) -> UserSettingsResponse:
    return await service.update(user, request)


__all__ = ["get_user_settings_service", "user_settings_router"]
