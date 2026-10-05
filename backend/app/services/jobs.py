from sqlalchemy.orm import Session

from app.adapters.base import JobAdapter
from app.adapters.greenhouse import GreenhouseAdapter, GreenhouseSourceError
from app.adapters.lever import LeverAdapter, LeverSourceError
from app.repositories.jobs import import_jobs
from app.schemas.jobs import (
    GreenhouseBoardError,
    GreenhouseImportResult,
    ImportResult,
    LeverImportResult,
    LeverSiteError,
)


def import_from_adapter(db: Session, adapter: JobAdapter) -> ImportResult:
    normalized_jobs = adapter.fetch_jobs()
    created, updated = import_jobs(db, normalized_jobs)
    return ImportResult(
        source=adapter.source_name,
        created=created,
        updated=updated,
        total=len(normalized_jobs),
    )


def import_greenhouse_boards(db: Session, board_tokens: list[str]) -> GreenhouseImportResult:
    created_total = 0
    updated_total = 0
    job_total = 0
    boards_succeeded = 0
    errors: list[GreenhouseBoardError] = []

    for board_token in board_tokens:
        try:
            adapter = GreenhouseAdapter(board_token)
            jobs = adapter.fetch_jobs()
        except GreenhouseSourceError as error:
            errors.append(GreenhouseBoardError(board_token=board_token, message=str(error)))
            continue

        created, updated = import_jobs(db, jobs)
        created_total += created
        updated_total += updated
        job_total += len(jobs)
        boards_succeeded += 1

    return GreenhouseImportResult(
        boards_configured=len(board_tokens),
        boards_succeeded=boards_succeeded,
        created=created_total,
        updated=updated_total,
        total=job_total,
        errors=errors,
    )


def import_lever_sites(db: Session, sites: list[str], region: str) -> LeverImportResult:
    created_total = 0
    updated_total = 0
    job_total = 0
    sites_succeeded = 0
    errors: list[LeverSiteError] = []

    for site in sites:
        try:
            jobs = LeverAdapter(site, region=region).fetch_jobs()
        except LeverSourceError as error:
            errors.append(LeverSiteError(site=site, message=str(error)))
            continue

        created, updated = import_jobs(db, jobs)
        created_total += created
        updated_total += updated
        job_total += len(jobs)
        sites_succeeded += 1

    return LeverImportResult(
        sites_configured=len(sites),
        sites_succeeded=sites_succeeded,
        created=created_total,
        updated=updated_total,
        total=job_total,
        errors=errors,
    )
