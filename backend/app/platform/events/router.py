from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import get_db
from app.platform.events.repository import EventRepository
from app.platform.events.schemas import EventCreate, EventRead
from app.platform.events.service import EventService

router = APIRouter(tags=["platform-events"])


def get_event_service(db: AsyncSession = Depends(get_db)) -> EventService:
    return EventService(EventRepository(db))


@router.post("/events", response_model=EventRead, status_code=201)
async def create_event(
    request: EventCreate,
    service: EventService = Depends(get_event_service),
) -> EventRead:
    return await service.create(request)


@router.get("/runs/{run_id}/events", response_model=list[EventRead])
async def list_run_events(
    run_id: str,
    service: EventService = Depends(get_event_service),
) -> list[EventRead]:
    return await service.list_for_run(run_id)
