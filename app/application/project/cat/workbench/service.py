from __future__ import annotations

import re
import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from tortoise.exceptions import IntegrityError

from .....models import DocumentSegment, SegmentLock, SegmentSuggestion, User
from .....repositories import CatRepository, MembershipRepository
from ...terminology.schemas import TerminologySearchRequest
from ...terminology.service import TerminologyService
from ....translation_memory.schemas import TranslationMemorySearchRequest
from ....translation_memory.service import TranslationMemoryService
from ...worldview.service import WorldviewService
from ..schemas import (
    QACheck,
    QAIssue,
    QARequest,
    QAResponse,
    SegmentChangeSummary,
    SegmentDetailResponse,
    SegmentLockRequest,
    SegmentLockRenewRequest,
    SegmentLockReleaseRequest,
    SegmentLockResponse,
    SegmentResponse,
    SegmentUpdateRequest,
    SuggestionRequest,
    SuggestionResponse,
    SuggestionsResponse,
)
from ...service import ProjectError, ProjectForbiddenError, ProjectNotFoundError


class CatError(ProjectError):
    code = "CAT_ERROR"


class CatNotFoundError(CatError):
    status_code = 404
    code = "SEGMENT_NOT_FOUND"


class CatForbiddenError(CatError):
    status_code = 403
    code = "CAT_FORBIDDEN"


class CatLockedError(CatError):
    status_code = 409
    code = "SEGMENT_LOCKED"


class CatVersionConflictError(CatError):
    status_code = 409
    code = "SEGMENT_VERSION_CONFLICT"


class CatStateConflictError(CatError):
    status_code = 409
    code = "SEGMENT_STATE_CONFLICT"


class CatValidationError(CatError):
    status_code = 422
    code = "CAT_INVALID"


class CatWorkbenchService:
    def __init__(
        self,
        *,
        repository: CatRepository | None = None,
        memberships: MembershipRepository | None = None,
        terminology: TerminologyService | None = None,
        worldview: WorldviewService | None = None,
        translation_memory: TranslationMemoryService | None = None,
    ) -> None:
        self._repository = repository or CatRepository()
        self._memberships = memberships or MembershipRepository()
        self._terminology = terminology or TerminologyService()
        self._worldview = worldview or WorldviewService()
        self._translation_memory = translation_memory or TranslationMemoryService()

    async def get(self, user: User, project_id: UUID, segment_id: UUID) -> SegmentDetailResponse:
        await self._membership(user, project_id)
        segment = await self._segment(project_id, segment_id)
        previous, following = await self._repository.neighbors(segment)
        lock = await self._active_lock(segment.id)
        terminology_matches = await self._terminology_matches(user, project_id, segment)
        worldview_matches = await self._worldview_matches(user, project_id, segment)
        return SegmentDetailResponse(
            segment=self._segment_response(segment),
            previous=self._segment_response(previous) if previous else None,
            next=self._segment_response(following) if following else None,
            lock=self._lock_response(lock) if lock else None,
            terminology_matches=terminology_matches,
            worldview_matches=worldview_matches,
            recent_changes=[SegmentChangeSummary.model_validate(item) for item in segment.change_history[-10:]],
        )

    async def lock(self, user: User, project_id: UUID, segment_id: UUID, request: SegmentLockRequest) -> SegmentLockResponse:
        await self._membership(user, project_id)
        segment = await self._segment(project_id, segment_id)
        existing = await self._active_lock(segment.id)
        now = datetime.now(timezone.utc)
        if existing and existing.locked_until > now:
            if existing.user_id == user.id:
                return self._lock_response(existing)
            raise CatLockedError("片段已被其他用户锁定")
        if existing:
            await self._repository.delete_lock(existing)
        try:
            lock = await self._repository.create_lock(
                segment=segment,
                user=user,
                lock_token=secrets.token_urlsafe(32),
                locked_until=now + timedelta(seconds=request.duration_seconds),
            )
        except IntegrityError as exc:
            raise CatLockedError("片段刚刚被其他用户锁定") from exc
        return self._lock_response(lock)

    async def renew(self, user: User, project_id: UUID, segment_id: UUID, request: SegmentLockRenewRequest) -> SegmentLockResponse:
        await self._membership(user, project_id)
        segment = await self._segment(project_id, segment_id)
        lock = await self._repository.get_lock(segment.id)
        self._ensure_owned_lock(lock, user, request.lock_token)
        now = datetime.now(timezone.utc)
        if lock.locked_until <= now:
            await self._repository.delete_lock(lock)
            raise CatLockedError("片段锁已过期")
        lock.locked_until = now + timedelta(seconds=request.duration_seconds)
        await self._repository.save_lock(lock, update_fields=["locked_until"])
        return self._lock_response(lock)

    async def release(self, user: User, project_id: UUID, segment_id: UUID, request: SegmentLockReleaseRequest) -> None:
        await self._membership(user, project_id)
        segment = await self._segment(project_id, segment_id)
        lock = await self._repository.get_lock(segment.id)
        self._ensure_owned_lock(lock, user, request.lock_token)
        await self._repository.delete_lock(lock)

    async def update(self, user: User, project_id: UUID, segment_id: UUID, request: SegmentUpdateRequest) -> SegmentResponse:
        await self._membership(user, project_id)
        segment = await self._segment(project_id, segment_id)
        lock = await self._repository.get_lock(segment.id)
        self._ensure_owned_lock(lock, user, request.lock_token)
        self._ensure_version(segment, request.version)
        if request.target is not None and len(request.target) > 1_000_000:
            raise CatValidationError("译文长度超过限制")
        if request.target is not None:
            segment.target_text = request.target
            segment.status = "translated" if request.target.strip() else "untranslated"
        if request.translator_note is not None or "translator_note" in request.model_fields_set:
            segment.translator_note = request.translator_note
        segment.workflow_state = "draft"
        segment.version += 1
        self._record_change(segment, "save_draft" if request.save_as == "draft" else "save_translation", user.id)
        await self._repository.save_segment(
            segment,
            update_fields=["target_text", "status", "workflow_state", "translator_note", "version", "change_history"],
        )
        return self._segment_response(segment)

    async def suggestions(
        self,
        user: User,
        project_id: UUID,
        segment_id: UUID,
        request: SuggestionRequest,
    ) -> SuggestionsResponse:
        await self._membership(user, project_id)
        segment = await self._segment(project_id, segment_id)
        if request.lock_token:
            self._ensure_owned_lock(await self._repository.get_lock(segment.id), user, request.lock_token)
        suggestions: list[SuggestionResponse] = []
        warnings: list[str] = []
        if "tm" in request.providers:
            started = perf_counter()
            try:
                result = await self._translation_memory.search(
                    user,
                    project_id,
                    TranslationMemorySearchRequest(
                        source_text=segment.source_text,
                        source_language=segment.source_language,
                        target_language=segment.target_language,
                        top_k=5,
                        match_mode="exact",
                    ),
                )
                for match in result.items:
                    suggestions.append(
                        await self._persist_suggestion(
                            segment,
                            source="tm",
                            text=match.target_text,
                            score=match.score,
                            evidence=[{"type": "tm", "id": str(match.entry_id)}] if request.include_explanation else [],
                            warnings=[],
                            latency_ms=int((perf_counter() - started) * 1000),
                        )
                    )
            except Exception:
                warnings.append("TM_UNAVAILABLE")
        if "terminology" in request.providers:
            try:
                matches = await self._terminology.search(
                    user,
                    project_id,
                    TerminologySearchRequest(
                        text=segment.source_text,
                        source_language=segment.source_language,
                        target_language=segment.target_language,
                    ),
                )
                for match in matches.items:
                    suggestions.append(
                        await self._persist_suggestion(
                            segment,
                            source="terminology",
                            text=match.target_term,
                            score=0.9,
                            evidence=[{"type": "terminology", "id": str(match.term_id)}] if request.include_explanation else [],
                            warnings=[],
                            latency_ms=None,
                        )
                    )
            except Exception:
                warnings.append("TERMINOLOGY_UNAVAILABLE")
        if "worldview" in request.providers:
            for match in await self._worldview_matches(user, project_id, segment):
                variant = match.get("target_term")
                if variant:
                    suggestions.append(
                        await self._persist_suggestion(
                            segment,
                            source="worldview",
                            text=variant,
                            score=0.85,
                            evidence=[{"type": "worldview", "id": match["id"]}] if request.include_explanation else [],
                            warnings=[],
                            latency_ms=None,
                        )
                    )
        for provider in ("rag", "llm"):
            if provider in request.providers:
                warnings.append(f"{provider.upper()}_PROVIDER_NOT_IMPLEMENTED")
        suggestions.sort(key=lambda item: (-item.score, item.source, str(item.id)))
        return SuggestionsResponse(segment_id=segment.id, suggestions=suggestions, warnings=sorted(set(warnings)))

    async def qa(self, user: User, project_id: UUID, segment_id: UUID, request: QARequest) -> QAResponse:
        await self._membership(user, project_id)
        segment = await self._segment(project_id, segment_id)
        issues = self._run_qa(segment, request.checks)
        if "terminology" in request.checks:
            issues.extend(await self._terminology_qa(user, project_id, segment))
        result = QAResponse(
            segment_id=segment.id,
            summary={
                "error": sum(issue.severity == "error" for issue in issues),
                "warning": sum(issue.severity == "warning" for issue in issues),
                "info": sum(issue.severity == "info" for issue in issues),
            },
            issues=issues,
        )
        if request.save_results:
            segment.qa_results = result.model_dump(mode="json")
            segment.qa_checked_at = datetime.now(timezone.utc)
            await self._repository.save_segment(segment, update_fields=["qa_results", "qa_checked_at"])
        return result

    async def _membership(self, user: User, project_id: UUID):
        membership = await self._memberships.find(project_id, user.id)
        if membership is None:
            raise ProjectNotFoundError("项目不存在或当前用户不可见")
        return membership

    async def _segment(self, project_id: UUID, segment_id: UUID) -> DocumentSegment:
        segment = await self._repository.get_segment(project_id, segment_id)
        if segment is None:
            raise CatNotFoundError("片段不存在或当前用户不可见")
        return segment

    async def _active_lock(self, segment_id: UUID) -> SegmentLock | None:
        lock = await self._repository.get_lock(segment_id)
        if lock and lock.locked_until <= datetime.now(timezone.utc):
            await self._repository.delete_lock(lock)
            return None
        return lock

    @staticmethod
    def _ensure_owned_lock(lock: SegmentLock | None, user: User, token: str) -> None:
        if lock is None or lock.lock_token != token:
            raise CatLockedError("当前用户没有该片段的有效锁")
        if lock.user_id != user.id:
            raise CatLockedError("片段由其他用户锁定")

    @staticmethod
    def _ensure_version(segment: DocumentSegment, version: int) -> None:
        if segment.version != version:
            raise CatVersionConflictError("片段版本已变化，请刷新后重试")

    @staticmethod
    def _record_change(segment: DocumentSegment, action: str, user_id: UUID) -> None:
        history = list(segment.change_history or [])
        history.append({"version": segment.version + 1, "action": action, "user_id": str(user_id), "changed_at": datetime.now(timezone.utc).isoformat()})
        segment.change_history = history[-20:]

    async def _persist_suggestion(self, segment: DocumentSegment, **values: Any) -> SuggestionResponse:
        record = await self._repository.create_suggestion(
            segment=segment,
            provider=values.pop("provider", "internal"),
            model=values.pop("model", None),
            context_version=values.pop("context_version", None),
            **values,
        )
        return SuggestionResponse(
            id=record.id,
            text=record.text,
            source=record.source,
            score=record.score,
            evidence=record.evidence,
            warnings=record.warnings,
        )

    async def _terminology_matches(self, user: User, project_id: UUID, segment: DocumentSegment) -> list[dict[str, Any]]:
        try:
            result = await self._terminology.search(
                user,
                project_id,
                TerminologySearchRequest(
                    text=segment.source_text,
                    source_language=segment.source_language,
                    target_language=segment.target_language,
                ),
            )
            return [item.model_dump(mode="json") for item in result.items]
        except Exception:
            return []

    async def _terminology_qa(self, user: User, project_id: UUID, segment: DocumentSegment) -> list[QAIssue]:
        if not segment.target_text:
            return []
        matches = await self._terminology_matches(user, project_id, segment)
        issues: list[QAIssue] = []
        for match in matches:
            target_term = match.get("target_term")
            if target_term and target_term.casefold() not in segment.target_text.casefold():
                issues.append(
                    QAIssue(
                        id=f"qa-{uuid4().hex[:10]}",
                        rule="terminology",
                        severity="warning",
                        message=f"建议使用官方术语 {target_term}",
                        source_span=[match.get("start", 0), match.get("end", 0)],
                        target_span=[0, len(segment.target_text)],
                        can_ignore=True,
                    )
                )
        return issues

    async def _worldview_matches(self, user: User, project_id: UUID, segment: DocumentSegment) -> list[dict[str, Any]]:
        try:
            page = await self._worldview.list_entries(user, project_id, entry_type=None, query=None, status="active", page_size=100, cursor=None)
        except Exception:
            return []
        source = segment.source_text.casefold()
        matches: list[dict[str, Any]] = []
        for entry in page.items:
            names = [entry.name, *entry.aliases]
            if any(name.casefold() in source for name in names if name):
                target = entry.language_variants.get(segment.target_language)
                matches.append({"id": str(entry.id), "name": entry.name, "target_term": target, "type": entry.type})
        return matches

    @staticmethod
    def _run_qa(segment: DocumentSegment, checks: list[QACheck]) -> list[QAIssue]:
        source = segment.source_text or ""
        target = segment.target_text or ""
        issues: list[QAIssue] = []
        if "placeholders" in checks:
            source_tokens = re.findall(r"\{[^{}]+\}|%\w+", source)
            target_tokens = re.findall(r"\{[^{}]+\}|%\w+", target)
            if Counter(source_tokens) != Counter(target_tokens):
                issues.append(QAIssue(id=f"qa-{uuid4().hex[:10]}", rule="placeholders", severity="error", message="占位符数量或名称不一致", source_span=[0, len(source)], target_span=[0, len(target)], can_ignore=False))
        if "numbers" in checks:
            number_pattern = r"\d+(?:[.,]\d+)?"
            if Counter(re.findall(number_pattern, source)) != Counter(re.findall(number_pattern, target)):
                issues.append(QAIssue(id=f"qa-{uuid4().hex[:10]}", rule="numbers", severity="error", message="数字数量或内容不一致", source_span=[0, len(source)], target_span=[0, len(target)], can_ignore=False))
        if "tags" in checks:
            if Counter(re.findall(r"<[^>]+>", source)) != Counter(re.findall(r"<[^>]+>", target)):
                issues.append(QAIssue(id=f"qa-{uuid4().hex[:10]}", rule="tags", severity="error", message="标记数量或内容不一致", source_span=[0, len(source)], target_span=[0, len(target)], can_ignore=False))
        if "length" in checks and target and len(target) > max(20, len(source) * 4):
            issues.append(QAIssue(id=f"qa-{uuid4().hex[:10]}", rule="length", severity="warning", message="译文长度明显超过源文", source_span=[0, len(source)], target_span=[0, len(target)], can_ignore=True))
        if "style" in checks and not target.strip():
            issues.append(QAIssue(id=f"qa-{uuid4().hex[:10]}", rule="style", severity="error", message="译文不能为空", source_span=[0, len(source)], target_span=[0, len(target)], can_ignore=False))
        return issues

    @staticmethod
    def _segment_response(segment: DocumentSegment | None) -> SegmentResponse:
        if segment is None:
            raise ValueError("segment is required")
        return SegmentResponse(
            id=segment.id,
            document_id=segment.document_id,
            segment_no=segment.segment_no,
            source=segment.source_text,
            target=segment.target_text,
            source_language=segment.source_language,
            target_language=segment.target_language,
            status=segment.status,
            workflow_state=segment.workflow_state,
            assigned_to=segment.assigned_to_id,
            translator_note=segment.translator_note,
            qa_results=segment.qa_results,
            version=segment.version,
            updated_at=segment.updated_at,
        )

    @staticmethod
    def _lock_response(lock: SegmentLock) -> SegmentLockResponse:
        return SegmentLockResponse(segment_id=lock.segment_id, lock_token=lock.lock_token, locked_by=lock.user_id, locked_until=lock.locked_until)


__all__ = [
    "CatError",
    "CatForbiddenError",
    "CatLockedError",
    "CatNotFoundError",
    "CatStateConflictError",
    "CatValidationError",
    "CatVersionConflictError",
    "CatWorkbenchService",
]
