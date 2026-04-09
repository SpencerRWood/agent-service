from app.platform.artifacts.models import Artifact
from app.platform.artifacts.repository import ArtifactRepository
from app.platform.artifacts.schemas import ArtifactCreate, ArtifactRead


class ArtifactService:
    def __init__(self, repository: ArtifactRepository) -> None:
        self._repository = repository

    async def create(self, request: ArtifactCreate) -> ArtifactRead:
        artifact = Artifact(
            run_id=request.run_id,
            run_step_id=request.run_step_id,
            artifact_type=request.artifact_type,
            title=request.title,
            content_json=request.content,
            uri=request.uri,
            provenance_json=request.provenance,
            status=request.status,
        )
        created = await self._repository.create(artifact)
        return ArtifactRead.model_validate(created)

    async def list_for_run(self, run_id: str) -> list[ArtifactRead]:
        artifacts = await self._repository.list_for_run(run_id)
        return [ArtifactRead.model_validate(artifact) for artifact in artifacts]
