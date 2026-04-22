from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class AgentCatalogConfigRecord(Base):
    __tablename__ = "platform_agent_catalog_configs"

    config_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    override_yaml: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    backend_models_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
