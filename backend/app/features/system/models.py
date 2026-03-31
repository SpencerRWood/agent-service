from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class HealthCheck(Base):
    __tablename__ = "health_check"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
