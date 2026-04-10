from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.execution_targets.models import ExecutionJob, ExecutionTarget


class ExecutionTargetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_target(self, target: ExecutionTarget) -> ExecutionTarget:
        if target.is_default:
            await self._clear_default_target()
        self._session.add(target)
        await self._session.commit()
        await self._session.refresh(target)
        return target

    async def list_targets(self) -> list[ExecutionTarget]:
        result = await self._session.execute(
            select(ExecutionTarget).order_by(
                ExecutionTarget.is_default.desc(), ExecutionTarget.id.asc()
            )
        )
        return list(result.scalars().all())

    async def list_enabled_targets_for_tool(self, tool_name: str) -> list[ExecutionTarget]:
        result = await self._session.execute(
            select(ExecutionTarget).where(ExecutionTarget.enabled.is_(True))
        )
        return [
            target
            for target in result.scalars().all()
            if _supports_tool(target.supported_tools_json or [], tool_name)
        ]

    async def get_target(self, target_id: str) -> ExecutionTarget | None:
        return await self._session.get(ExecutionTarget, target_id)

    async def update_target(self, target: ExecutionTarget) -> ExecutionTarget:
        if target.is_default:
            await self._clear_default_target(except_target_id=target.id)
        await self._session.commit()
        await self._session.refresh(target)
        return target

    async def get_default_target(self, tool_name: str | None = None) -> ExecutionTarget | None:
        stmt = select(ExecutionTarget).where(
            ExecutionTarget.enabled.is_(True),
            ExecutionTarget.is_default.is_(True),
        )
        result = await self._session.execute(stmt)
        target = result.scalar_one_or_none()
        if target is None:
            return None
        if tool_name is not None and not _supports_tool(
            target.supported_tools_json or [], tool_name
        ):
            return None
        return target

    async def create_job(self, job: ExecutionJob) -> ExecutionJob:
        self._session.add(job)
        await self._session.commit()
        await self._session.refresh(job)
        return job

    async def get_job(self, job_id: str) -> ExecutionJob | None:
        self._session.expire_all()
        result = await self._session.execute(select(ExecutionJob).where(ExecutionJob.id == job_id))
        return result.scalar_one_or_none()

    async def list_jobs(
        self, *, target_id: str | None = None, limit: int = 50
    ) -> list[ExecutionJob]:
        stmt = select(ExecutionJob).order_by(ExecutionJob.created_at.desc()).limit(limit)
        if target_id is not None:
            stmt = stmt.where(ExecutionJob.target_id == target_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def claim_next_job(
        self,
        *,
        target_id: str,
        worker_id: str,
        supported_tools: list[str],
    ) -> ExecutionJob | None:
        stmt = (
            select(ExecutionJob)
            .where(
                ExecutionJob.target_id == target_id,
                ExecutionJob.status == "queued",
            )
            .order_by(ExecutionJob.created_at.asc())
        )
        result = await self._session.execute(stmt)
        for job in result.scalars().all():
            if supported_tools and not _supports_tool(supported_tools, job.tool_name):
                continue
            not_before = (job.payload_json or {}).get("available_at")
            if isinstance(not_before, str):
                try:
                    available_at = datetime.fromisoformat(not_before.replace("Z", "+00:00"))
                except ValueError:
                    available_at = None
                if available_at is not None and available_at > datetime.now(UTC):
                    continue
            job.status = "claimed"
            job.claimed_by = worker_id
            job.claimed_at = datetime.now(UTC)
            await self._session.commit()
            await self._session.refresh(job)
            return job
        return None

    async def complete_job(
        self,
        job: ExecutionJob,
        *,
        result_payload: dict,
    ) -> ExecutionJob:
        job.status = "completed"
        job.result_json = result_payload
        job.completed_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(job)
        return job

    async def fail_job(self, job: ExecutionJob, *, error_payload: dict) -> ExecutionJob:
        job.status = "failed"
        job.error_json = error_payload
        job.completed_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(job)
        return job

    async def requeue_job(
        self,
        job: ExecutionJob,
        *,
        payload: dict,
        available_at: datetime | None,
        reason: dict,
    ) -> ExecutionJob:
        payload_with_schedule = {
            **payload,
            "available_at": available_at.isoformat() if available_at is not None else None,
            "defer_reason": reason,
        }
        job.status = "queued"
        job.payload_json = payload_with_schedule
        job.error_json = None
        job.result_json = None
        job.claimed_by = None
        job.claimed_at = None
        job.completed_at = None
        await self._session.commit()
        await self._session.refresh(job)
        return job

    async def mark_seen(self, target: ExecutionTarget) -> ExecutionTarget:
        target.last_seen_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(target)
        return target

    async def _clear_default_target(self, except_target_id: str | None = None) -> None:
        result = await self._session.execute(
            select(ExecutionTarget).where(ExecutionTarget.is_default.is_(True))
        )
        for target in result.scalars().all():
            if except_target_id is not None and target.id == except_target_id:
                continue
            target.is_default = False


def _supports_tool(supported_tools: list[str], tool_name: str) -> bool:
    normalized = {str(tool).strip() for tool in supported_tools}
    return "*" in normalized or tool_name in normalized
