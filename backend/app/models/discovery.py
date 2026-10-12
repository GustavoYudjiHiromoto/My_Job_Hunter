from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.job import Job, JobSource
    from app.models.monitoring import ImportRunSource


class DiscoveryQuery(Base):
    """Consulta determinística executada por um provider numa coleta de descoberta."""

    __tablename__ = "discovery_queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_run_source_id: Mapped[int] = mapped_column(
        ForeignKey("import_run_sources.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), index=True)
    strategy: Mapped[str] = mapped_column(String(40))
    query_hash: Mapped[str] = mapped_column(String(64), index=True)
    search_terms: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(200))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created: Mapped[int] = mapped_column(default=0)
    updated: Mapped[int] = mapped_column(default=0)
    total: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_run: Mapped["ImportRunSource"] = relationship(back_populates="discovery_queries")
    discoveries: Mapped[list["JobDiscovery"]] = relationship(
        back_populates="query", cascade="all, delete-orphan"
    )


class JobDiscovery(Base):
    """Proveniência que registra qual busca encontrou uma origem de vaga."""

    __tablename__ = "job_discoveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    job_source_id: Mapped[int] = mapped_column(
        ForeignKey("job_sources.id", ondelete="CASCADE"), index=True
    )
    query_id: Mapped[int] = mapped_column(ForeignKey("discovery_queries.id", ondelete="CASCADE"), index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    job: Mapped["Job"] = relationship()
    job_source: Mapped["JobSource"] = relationship()
    query: Mapped[DiscoveryQuery] = relationship(back_populates="discoveries")

    __table_args__ = (UniqueConstraint("job_source_id", "query_id", name="uq_job_discoveries_source_query"),)


class JobEligibility(Base):
    """Resultado do ponto de extensão do pré-filtro, sem regras ainda configuradas."""

    __tablename__ = "job_eligibility"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="eligible", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    policy_version: Mapped[str] = mapped_column(String(40), default="unconfigured")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    job: Mapped["Job"] = relationship()


Index("ix_discovery_queries_run_provider", DiscoveryQuery.import_run_source_id, DiscoveryQuery.provider)
