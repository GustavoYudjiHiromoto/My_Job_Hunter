from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.discovery import DiscoveryQuery


class ImportRun(Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    requested_source: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list["ImportRunSource"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ImportRunSource.id"
    )

    __table_args__ = (Index("ix_import_runs_started_at", started_at.desc()),)


class ImportRunSource(Base):
    __tablename__ = "import_run_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_run_id: Mapped[int] = mapped_column(ForeignKey("import_runs.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))
    scope: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20))
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    run: Mapped[ImportRun] = relationship(back_populates="sources")
    discovery_queries: Mapped[list["DiscoveryQuery"]] = relationship(
        back_populates="source_run", cascade="all, delete-orphan", order_by="DiscoveryQuery.id"
    )

    __table_args__ = (UniqueConstraint("import_run_id", "source", "scope"),)


class JobSourceObservation(Base):
    __tablename__ = "job_source_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_source_id: Mapped[int] = mapped_column(
        ForeignKey("job_sources.id", ondelete="CASCADE"), unique=True, index=True
    )
    scope: Mapped[str] = mapped_column(String(120), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    missed_complete_runs: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    last_import_run_id: Mapped[int | None] = mapped_column(ForeignKey("import_runs.id", ondelete="SET NULL"))
