import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.adapters.base import JobAdapter
from app.adapters.greenhouse import GreenhouseAdapter, GreenhouseSourceError
from app.adapters.lever import LeverAdapter, LeverSourceError
from app.core.config import get_greenhouse_board_tokens, get_lever_region, get_lever_sites
from app.models import ImportRun, ImportRunSource
from app.repositories.jobs import import_jobs, reconcile_source_snapshot
from app.schemas.jobs import ImportResult, NormalizedJob
from app.services.import_lock import ImportAlreadyRunning, import_lock

logger = logging.getLogger(__name__)
RequestedSource = Literal["all", "greenhouse", "lever"]


@dataclass
class SourceTarget:
    source: str
    scope: str
    fetch: Callable[[], list[NormalizedJob]]


def import_from_adapter(db: Session, adapter: JobAdapter) -> ImportResult:
    normalized_jobs = adapter.fetch_jobs()
    created, updated = import_jobs(db, normalized_jobs)
    return ImportResult(
        source=adapter.source_name,
        created=created,
        updated=updated,
        total=len(normalized_jobs),
    )


def _targets(
    requested_source: RequestedSource,
    greenhouse_tokens: list[str] | None = None,
    lever_sites: list[str] | None = None,
    lever_region: str | None = None,
) -> list[SourceTarget]:
    targets: list[SourceTarget] = []
    if requested_source in ("all", "greenhouse"):
        board_tokens = get_greenhouse_board_tokens() if greenhouse_tokens is None else greenhouse_tokens
        targets.extend(
            SourceTarget("greenhouse", token, lambda token=token: GreenhouseAdapter(token).fetch_jobs())
            for token in board_tokens
        )
    if requested_source in ("all", "lever"):
        sites = get_lever_sites() if lever_sites is None else lever_sites
        region = get_lever_region() if lever_region is None else lever_region
        targets.extend(
            SourceTarget(
                "lever",
                site,
                lambda site=site, region=region: LeverAdapter(site, region=region).fetch_jobs(),
            )
            for site in sites
        )
    return targets


def _source_error(source: str, error: Exception) -> str:
    if isinstance(error, (GreenhouseSourceError, LeverSourceError)):
        return str(error)
    logger.exception("Falha inesperada ao coletar %s", source)
    return f"Falha inesperada ao processar a origem {source}. Consulte o log do backend."


def _load_run(db: Session, run_id: int) -> ImportRun:
    return db.scalar(select(ImportRun).options(selectinload(ImportRun.sources)).where(ImportRun.id == run_id))


def _finish_run(db: Session, run: ImportRun) -> ImportRun:
    sources = list(run.sources)
    succeeded = sum(source.status == "succeeded" for source in sources)
    failed = sum(source.status == "failed" for source in sources)
    run.created = sum(source.created for source in sources)
    run.updated = sum(source.updated for source in sources)
    run.total = sum(source.total for source in sources)
    if failed and succeeded:
        run.status = "partial"
    elif failed or not sources:
        run.status = "failed"
    else:
        run.status = "succeeded"
    run.finished_at = datetime.now(UTC)
    db.commit()
    return _load_run(db, run.id)


def _record_skipped(db: Session, requested_source: RequestedSource) -> ImportRun:
    run = ImportRun(
        requested_source=requested_source,
        status="skipped",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        error="Já existe uma coleta em andamento.",
    )
    db.add(run)
    db.commit()
    return _load_run(db, run.id)


def _mark_abandoned_runs(db: Session) -> None:
    abandoned = list(db.scalars(select(ImportRun).where(ImportRun.status.in_(("pending", "running")))).all())
    if not abandoned:
        return
    now = datetime.now(UTC)
    for run in abandoned:
        run.status = "interrupted"
        run.finished_at = now
        run.error = "O processo terminou antes de registrar o resultado da coleta."
        for source in run.sources:
            if source.status == "pending":
                source.status = "failed"
                source.error = "A unidade não foi concluída porque a execução foi interrompida."
    db.commit()


def run_import(
    db: Session,
    requested_source: RequestedSource = "all",
    greenhouse_tokens: list[str] | None = None,
    lever_sites: list[str] | None = None,
    lever_region: str | None = None,
) -> ImportRun:
    try:
        lock = import_lock(db)
        lock.__enter__()
    except ImportAlreadyRunning:
        return _record_skipped(db, requested_source)

    try:
        _mark_abandoned_runs(db)
        now = datetime.now(UTC)
        run = ImportRun(
            requested_source=requested_source,
            status="pending",
            started_at=now,
        )
        db.add(run)
        db.commit()
        run.status = "running"
        db.commit()

        targets = _targets(requested_source, greenhouse_tokens, lever_sites, lever_region)
        if not targets:
            run.error = "Nenhuma fonte configurada para esta execução."
            return _finish_run(db, run)

        for target in targets:
            result = ImportRunSource(
                import_run_id=run.id,
                source=target.source,
                scope=target.scope,
                status="pending",
            )
            db.add(result)
            db.commit()
            try:
                jobs = target.fetch()
                created, updated = import_jobs(db, jobs, commit=False)
                reconcile_source_snapshot(
                    db,
                    target.source,
                    target.scope,
                    jobs,
                    import_run_id=run.id,
                    collected_at=datetime.now(UTC),
                )
                result = db.get(ImportRunSource, result.id)
                result.status = "succeeded"
                result.created = created
                result.updated = updated
                result.total = len(jobs)
                db.commit()
            except (GreenhouseSourceError, LeverSourceError) as error:
                db.rollback()
                result = db.get(ImportRunSource, result.id)
                result.status = "failed"
                result.error = _source_error(target.source, error)
                db.commit()
            except Exception as error:
                db.rollback()
                result = db.get(ImportRunSource, result.id)
                result.status = "failed"
                result.error = _source_error(target.source, error)
                db.commit()

        run = _load_run(db, run.id)
        return _finish_run(db, run)
    except Exception:
        db.rollback()
        raise
    finally:
        lock.__exit__(None, None, None)


def latest_import_run(db: Session) -> ImportRun | None:
    return db.scalar(
        select(ImportRun)
        .options(selectinload(ImportRun.sources))
        .order_by(ImportRun.started_at.desc(), ImportRun.id.desc())
        .limit(1)
    )
