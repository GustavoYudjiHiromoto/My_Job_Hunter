from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Job, JobSource
from app.schemas.jobs import NormalizedJob

JOB_FIELDS = (
    "title",
    "company",
    "description",
    "location",
    "workplace_type",
    "seniority",
    "employment_type",
    "salary_min",
    "salary_max",
    "salary_currency",
    "published_at",
    "status",
)


def import_jobs(db: Session, jobs: list[NormalizedJob]) -> tuple[int, int]:
    created = 0
    updated = 0

    for normalized in jobs:
        source_record = db.scalar(
            select(JobSource).where(
                JobSource.source == normalized.source,
                JobSource.external_id == normalized.external_id,
            )
        )
        if source_record is None:
            job = Job(**{field: getattr(normalized, field) for field in JOB_FIELDS})
            source_record = JobSource(
                source=normalized.source,
                external_id=normalized.external_id,
                source_url=str(normalized.source_url),
                original_payload=normalized.original_payload,
                job=job,
            )
            db.add(source_record)
            created += 1
        else:
            job = source_record.job
            for field in JOB_FIELDS:
                setattr(job, field, getattr(normalized, field))
            source_record.source_url = str(normalized.source_url)
            source_record.original_payload = normalized.original_payload
            updated += 1

    db.commit()
    return created, updated


def list_jobs(db: Session) -> list[Job]:
    statement = (
        select(Job)
        .options(selectinload(Job.sources))
        .order_by(Job.published_at.desc().nulls_last(), Job.id.desc())
    )
    return list(db.scalars(statement).all())


def get_job(db: Session, job_id: int) -> Job | None:
    statement = select(Job).options(selectinload(Job.sources)).where(Job.id == job_id)
    return db.scalar(statement)
