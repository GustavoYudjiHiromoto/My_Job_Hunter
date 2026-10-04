from sqlalchemy.orm import Session

from app.adapters.base import JobAdapter
from app.repositories.jobs import import_jobs
from app.schemas.jobs import ImportResult


def import_from_adapter(db: Session, adapter: JobAdapter) -> ImportResult:
    normalized_jobs = adapter.fetch_jobs()
    created, updated = import_jobs(db, normalized_jobs)
    return ImportResult(
        source=adapter.source_name,
        created=created,
        updated=updated,
        total=len(normalized_jobs),
    )
