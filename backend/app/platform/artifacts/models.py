from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class Artifact(Base):
    __tablename__ = "platform_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_runs.id"), nullable=True, index=True
    )
    run_step_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_run_steps.id"), nullable=True, index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
