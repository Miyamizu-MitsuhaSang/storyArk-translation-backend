from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from starlette.responses import Response

from ......application.project.terminology.schemas import (
    TerminologyBaseCreateRequest,
    TerminologyBasePage,
    TerminologyBaseResponse,
    TerminologySearchRequest,
    TerminologySearchResponse,
    TerminologyTermCreateRequest,
    TerminologyTermPage,
    TerminologyTermQuery,
    TerminologyTermResponse,
    TerminologyTermUpdateRequest,
)
from ......application.project.terminology.service import TerminologyService
from ......models import User
from .....shared.dependencies import get_current_user
from .dependencies import get_terminology_service


project_terminology_router = APIRouter()


@project_terminology_router.get(
    "/terminology-bases",
    response_model=TerminologyBasePage,
    description="返回当前项目的术语库列表，包括语言对、优先级、状态和术语数量；项目成员可读取。",
)
async def list_terminology_bases(
    project_id: UUID,
    page_size: int = Query(default=20, ge=1, le=100, description="每页返回数量。"),
    cursor: str | None = Query(default=None, description="不透明分页游标。"),
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyBasePage:
    return await service.list_bases(user, project_id, page_size=page_size, cursor=cursor)


@project_terminology_router.post(
    "/terminology-bases",
    response_model=TerminologyBaseResponse,
    status_code=201,
    description="创建项目术语库；需要 owner 或 manager 角色。",
)
async def create_terminology_base(
    project_id: UUID,
    request: TerminologyBaseCreateRequest,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyBaseResponse:
    return await service.create_base(user, project_id, request)


@project_terminology_router.get(
    "/terminology-bases/{base_id}/terms",
    response_model=TerminologyTermPage,
    description="按关键词、术语类型、状态、目标语言和游标分页查询术语；项目成员可读取。",
)
async def list_terminology_terms(
    project_id: UUID,
    base_id: UUID,
    query: TerminologyTermQuery = Depends(),
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyTermPage:
    return await service.list_terms(user, project_id, base_id, query)


@project_terminology_router.post(
    "/terminology-bases/{base_id}/terms",
    response_model=TerminologyTermResponse,
    status_code=201,
    description="创建术语并记录初始版本；需要 owner 或 manager 角色。",
)
async def create_terminology_term(
    project_id: UUID,
    base_id: UUID,
    request: TerminologyTermCreateRequest,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyTermResponse:
    return await service.create_term(user, project_id, base_id, request)


@project_terminology_router.get(
    "/terminology-bases/{base_id}/terms/{term_id}",
    response_model=TerminologyTermResponse,
    description="返回术语的语言变体、状态、来源、版本和历史摘要；项目成员可读取。",
)
async def get_terminology_term(
    project_id: UUID,
    base_id: UUID,
    term_id: UUID,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyTermResponse:
    return await service.get_term(user, project_id, base_id, term_id)


@project_terminology_router.patch(
    "/terminology-bases/{base_id}/terms/{term_id}",
    response_model=TerminologyTermResponse,
    description="更新术语并生成新的版本快照；需要 owner 或 manager 角色。",
)
async def update_terminology_term(
    project_id: UUID,
    base_id: UUID,
    term_id: UUID,
    request: TerminologyTermUpdateRequest,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyTermResponse:
    return await service.update_term(user, project_id, base_id, term_id, request)


@project_terminology_router.delete(
    "/terminology-bases/{base_id}/terms/{term_id}",
    status_code=204,
    description="软删除或归档术语并保留版本历史；需要 owner 或 manager 角色。",
)
async def delete_terminology_term(
    project_id: UUID,
    base_id: UUID,
    term_id: UUID,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> Response:
    await service.delete_term(user, project_id, base_id, term_id)
    return Response(status_code=204)


@project_terminology_router.post(
    "/terminology/search",
    response_model=TerminologySearchResponse,
    description="在当前项目 active 术语库中查询文本命中，返回 approved、suggested 和可选 forbidden 译法及其位置。",
)
async def search_terminology(
    project_id: UUID,
    request: TerminologySearchRequest,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologySearchResponse:
    return await service.search(user, project_id, request)
