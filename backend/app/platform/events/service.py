from app.platform.events.models import Event
from app.platform.events.repository import EventRepository
from app.platform.events.schemas import EventCreate, EventRead


class EventService:
    def __init__(self, repository: EventRepository) -> None:
        self._repository = repository

    async def create(self, request: EventCreate) -> EventRead:
        event = Event(
            run_id=request.run_id,
            run_step_id=request.run_step_id,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            event_type=request.event_type,
            payload_json=request.payload,
            actor_type=request.actor_type,
            actor_id=request.actor_id,
            trace_id=request.trace_id,
        )
        created = await self._repository.create(event)
        return EventRead.model_validate(created)

    async def list_for_run(self, run_id: str) -> list[EventRead]:
        events = await self._repository.list_for_run(run_id)
        return [EventRead.model_validate(event) for event in events]
