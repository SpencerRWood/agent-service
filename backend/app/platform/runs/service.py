from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.platform.runs.models import Run, RunStep
from app.platform.runs.repository import RunRepository
from app.platform.runs.schemas import RunCreate, RunRead, RunStepCreate, RunStepRead


class RunService:
    def __init__(self, repository: RunRepository) -> None:
        self._repository = repository

    async def create_run(self, request: RunCreate) -> RunRead:
        run, _created = await self.create_or_get_run(request)
        return run

    async def create_or_get_run(self, request: RunCreate) -> tuple[RunRead, bool]:
        run = Run(
            idempotency_key=request.idempotency_key,
            prompt_id=request.prompt_id,
            intent_id=request.intent_id,
            status=request.status,
        )
        try:
            created = await self._repository.create_run(run)
        except IntegrityError:
            if request.idempotency_key is None:
                raise
            existing = await self._repository.get_run_by_idempotency_key(request.idempotency_key)
            if existing is None:
                raise
            return RunRead.model_validate(existing), False
        return RunRead.model_validate(created), True

    async def get_run(self, run_id: str) -> RunRead:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        return RunRead.model_validate(run)

    async def get_run_by_idempotency_key(self, idempotency_key: str) -> RunRead | None:
        run = await self._repository.get_run_by_idempotency_key(idempotency_key)
        if run is None:
            return None
        return RunRead.model_validate(run)

    async def create_step(self, run_id: str, request: RunStepCreate) -> RunStepRead:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

        step = RunStep(
            run_id=run_id,
            step_type=request.step_type,
            title=request.title,
            status=request.status,
            sequence_index=request.sequence_index,
            input_json=request.input,
        )
        created = await self._repository.create_step(step)
        return RunStepRead.model_validate(created)

    async def list_steps(self, run_id: str) -> list[RunStepRead]:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        steps = await self._repository.list_steps(run_id)
        return [RunStepRead.model_validate(step) for step in steps]

    async def list_recent_steps(self, *, limit: int = 50) -> list[RunStepRead]:
        steps = await self._repository.list_recent_steps(limit=limit)
        return [RunStepRead.model_validate(step) for step in steps]

    async def update_run_status(self, run_id: str, status_value: str) -> RunRead:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        run.status = status_value
        updated = await self._repository.update_run(run)
        return RunRead.model_validate(updated)

    async def update_step_status(
        self,
        step_id: str,
        *,
        status_value: str,
        output: dict | None = None,
    ) -> RunStepRead:
        step = await self._repository.get_step(step_id)
        if step is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run step not found")
        step.status = status_value
        if output is not None:
            step.output_json = {**(step.output_json or {}), **output}
        updated = await self._repository.update_step(step)
        return RunStepRead.model_validate(updated)
