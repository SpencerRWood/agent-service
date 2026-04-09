from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class ToolDefinitionRecord(Base):
    __tablename__ = "platform_tool_definitions"

    tool_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    input_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    side_effect_class: Mapped[str] = mapped_column(String(32), nullable=False)
    destructive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    approval_policy_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="sync")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
