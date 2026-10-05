import re
import unicodedata
from urllib.parse import urlsplit

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
    existing_jobs = list(db.scalars(select(Job).options(selectinload(Job.sources))).unique().all())
    jobs_by_signature: dict[tuple[str, str, str], list[Job]] = {}
    jobs_by_url: dict[str, list[Job]] = {}
    for job in existing_jobs:
        _index_job(job, jobs_by_signature, jobs_by_url)

    for normalized in jobs:
        source_record = db.scalar(
            select(JobSource).where(
                JobSource.source == normalized.source,
                JobSource.external_id == normalized.external_id,
            )
        )
        if source_record is None:
            possible_matches = _find_matches(normalized, jobs_by_signature, jobs_by_url)
            matching_job = possible_matches[0] if len(possible_matches) == 1 else None
            if matching_job is not None and _is_cross_source_match(matching_job, normalized.source):
                job = matching_job
                _fill_missing_job_fields(job, normalized)
                updated += 1
            else:
                job = Job(**{field: getattr(normalized, field) for field in JOB_FIELDS})
                existing_jobs.append(job)
                created += 1

            source_record = JobSource(
                source=normalized.source,
                external_id=normalized.external_id,
                source_url=str(normalized.source_url),
                original_payload=normalized.original_payload,
                job=job,
            )
            db.add(source_record)
            _index_job(job, jobs_by_signature, jobs_by_url)
        else:
            job = source_record.job
            possible_matches = _find_matches(normalized, jobs_by_signature, jobs_by_url)
            duplicate_matches = [candidate for candidate in possible_matches if candidate is not job]
            if len(duplicate_matches) == 1 and _is_cross_source_match(
                duplicate_matches[0], normalized.source
            ):
                canonical_job = duplicate_matches[0]
                _remove_job_index(job, jobs_by_signature, jobs_by_url)
                _merge_duplicate_job(db, job, canonical_job, normalized)
                _index_job(canonical_job, jobs_by_signature, jobs_by_url)
                job = canonical_job
            if len(job.sources) > 1:
                _fill_missing_job_fields(job, normalized)
            else:
                for field in JOB_FIELDS:
                    setattr(job, field, getattr(normalized, field))
            source_record.source_url = str(normalized.source_url)
            source_record.original_payload = normalized.original_payload
            updated += 1

    db.commit()
    return created, updated


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.casefold()))


def _job_signature(title: str, company: str, location: str | None) -> tuple[str, str, str] | None:
    normalized_title = _normalize_text(title)
    normalized_company = _normalize_text(company)
    normalized_location = _normalize_text(location)
    if not normalized_title or not normalized_company or not normalized_location:
        return None
    return normalized_title, normalized_company, normalized_location


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}{path}{query}"


def _index_job(
    job: Job,
    jobs_by_signature: dict[tuple[str, str, str], list[Job]],
    jobs_by_url: dict[str, list[Job]],
) -> None:
    signature = _job_signature(job.title, job.company, job.location)
    if signature is not None:
        jobs_by_signature.setdefault(signature, []).append(job)
    for source in job.sources:
        canonical_url = _canonical_url(source.source_url)
        if canonical_url:
            jobs_by_url.setdefault(canonical_url, []).append(job)


def _find_matches(
    normalized: NormalizedJob,
    jobs_by_signature: dict[tuple[str, str, str], list[Job]],
    jobs_by_url: dict[str, list[Job]],
) -> list[Job]:
    candidates: dict[int, Job] = {}
    signature = _job_signature(normalized.title, normalized.company, normalized.location)
    if signature is not None:
        candidates.update((id(job), job) for job in jobs_by_signature.get(signature, []))
    canonical_url = _canonical_url(str(normalized.source_url))
    if canonical_url:
        candidates.update((id(job), job) for job in jobs_by_url.get(canonical_url, []))
    return list(candidates.values())


def _is_cross_source_match(job: Job, source_name: str) -> bool:
    return bool(job.sources) and all(source.source != source_name for source in job.sources)


def _fill_missing_job_fields(job: Job, normalized: NormalizedJob) -> None:
    for field in JOB_FIELDS:
        current = getattr(job, field)
        incoming = getattr(normalized, field)
        if current is None or current == "" or (field == "status" and current == "unknown"):
            if incoming is not None and incoming != "":
                setattr(job, field, incoming)


def _merge_duplicate_job(
    db: Session,
    duplicate: Job,
    canonical: Job,
    normalized: NormalizedJob,
) -> None:
    _fill_missing_job_fields(canonical, normalized)
    for field in JOB_FIELDS:
        current = getattr(canonical, field)
        previous = getattr(duplicate, field)
        if (current is None or current == "") and previous is not None and previous != "":
            setattr(canonical, field, previous)
    for source in list(duplicate.sources):
        source.job = canonical
    db.delete(duplicate)


def _remove_job_index(
    job: Job,
    jobs_by_signature: dict[tuple[str, str, str], list[Job]],
    jobs_by_url: dict[str, list[Job]],
) -> None:
    for index in (jobs_by_signature, jobs_by_url):
        for key in list(index):
            remaining = [candidate for candidate in index[key] if candidate is not job]
            if remaining:
                index[key] = remaining
            else:
                del index[key]


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
