import re
import unicodedata
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AIJobAnalysis, Job, JobDiscovery, JobEligibility, JobSource, JobSourceObservation
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


def import_jobs(
    db: Session,
    jobs: list[NormalizedJob],
    commit: bool = True,
    new_job_ids: set[int] | None = None,
) -> tuple[int, int]:
    created = 0
    updated = 0
    new_jobs: list[Job] = []
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
                new_jobs.append(job)
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

    if new_job_ids is not None:
        db.flush()
        new_job_ids.update(job.id for job in new_jobs if job.id is not None)
    if commit:
        db.commit()
    return created, updated


def reconcile_source_snapshot(
    db: Session,
    source: str,
    scope: str,
    jobs: list[NormalizedJob],
    import_run_id: int,
    collected_at: datetime,
) -> None:
    """Update source observations and conservatively close jobs after two misses."""
    db.flush()
    observed_ids = {job.external_id for job in jobs}
    source_records = list(db.scalars(select(JobSource).where(JobSource.source == source)).all())
    affected_job_ids: set[int] = set()

    for source_record in source_records:
        record_scope = source_record.external_id.partition(":")[0]
        if record_scope != scope:
            continue
        affected_job_ids.add(source_record.job_id)
        observation = db.scalar(
            select(JobSourceObservation).where(JobSourceObservation.job_source_id == source_record.id)
        )
        if observation is None:
            observation = JobSourceObservation(
                job_source_id=source_record.id,
                scope=scope,
                last_seen_at=None,
                missed_complete_runs=0,
                is_active=True,
            )
            db.add(observation)

        observation.scope = scope
        observation.last_import_run_id = import_run_id
        if source_record.external_id in observed_ids:
            observation.last_seen_at = collected_at
            observation.missed_complete_runs = 0
            observation.is_active = True
        else:
            observation.missed_complete_runs += 1
            if observation.missed_complete_runs >= 2:
                observation.is_active = False

    db.flush()
    for job_id in affected_job_ids:
        job = db.get(Job, job_id)
        if job is None:
            continue
        records = list(db.scalars(select(JobSource).where(JobSource.job_id == job_id)).all())
        observations = {
            record.id: db.scalar(
                select(JobSourceObservation).where(JobSourceObservation.job_source_id == record.id)
            )
            for record in records
        }
        # Origens sem monitoramento permanecem potencialmente ativas; fixtures são demonstrações.
        if any(
            record.source != "fixture"
            and (observations[record.id] is None or observations[record.id].is_active)
            for record in records
        ):
            job.status = "open"
        else:
            job.status = "closed"


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
        if field == "status" and incoming == "open":
            job.status = "open"
            continue
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

    _merge_discovery_metadata(db, duplicate, canonical)
    _merge_ai_analysis(db, duplicate, canonical)
    for source in list(duplicate.sources):
        source.job = canonical
    # Persist the FK reassignment before deleting the old parent, independent
    # of SQLite's connection-level foreign-key pragma and ORM delete ordering.
    db.flush()
    db.delete(duplicate)


def _merge_ai_analysis(db: Session, duplicate: Job, canonical: Job) -> None:
    """Keep one cached evaluation attached to the canonical job during deduplication."""
    duplicate_analysis = db.scalar(
        select(AIJobAnalysis).where(AIJobAnalysis.job_id == duplicate.id)
    )
    if duplicate_analysis is None:
        return
    canonical_analysis = db.scalar(
        select(AIJobAnalysis).where(AIJobAnalysis.job_id == canonical.id)
    )
    if canonical_analysis is None:
        duplicate_analysis.job_id = canonical.id
    else:
        # The canonical assessment remains authoritative; duplicate analyses are
        # reproducible and will be recalculated if its current input hash differs.
        db.delete(duplicate_analysis)


def _datetime_key(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _merge_discovery_metadata(db: Session, duplicate: Job, canonical: Job) -> None:
    """Move M9 metadata before deleting its owning job, in the current transaction."""
    canonical_discoveries = list(
        db.scalars(select(JobDiscovery).where(JobDiscovery.job_id == canonical.id)).all()
    )
    discoveries_by_key = {
        (item.job_source_id, item.query_id): item for item in canonical_discoveries
    }
    duplicate_discoveries = list(
        db.scalars(select(JobDiscovery).where(JobDiscovery.job_id == duplicate.id)).all()
    )
    for item in duplicate_discoveries:
        existing = discoveries_by_key.get((item.job_source_id, item.query_id))
        if existing is None:
            item.job_id = canonical.id
            discoveries_by_key[(item.job_source_id, item.query_id)] = item
        else:
            if _datetime_key(item.discovered_at) < _datetime_key(existing.discovered_at):
                existing.discovered_at = item.discovered_at
            db.delete(item)

    duplicate_eligibility = db.scalar(
        select(JobEligibility).where(JobEligibility.job_id == duplicate.id)
    )
    if duplicate_eligibility is None:
        return

    canonical_eligibility = db.scalar(
        select(JobEligibility).where(JobEligibility.job_id == canonical.id)
    )
    if canonical_eligibility is None:
        duplicate_eligibility.job_id = canonical.id
        return

    # Keep the canonical row identity and newest evaluation as current; retain the
    # other complete evaluation as an audit note so its reason/policy are not lost.
    if _datetime_key(duplicate_eligibility.evaluated_at) > _datetime_key(
        canonical_eligibility.evaluated_at
    ):
        current, previous = duplicate_eligibility, canonical_eligibility
    else:
        current, previous = canonical_eligibility, duplicate_eligibility

    canonical_eligibility.status = current.status
    canonical_eligibility.policy_version = current.policy_version
    canonical_eligibility.evaluated_at = current.evaluated_at
    previous_snapshot = (
        f"[Avaliação consolidada] status={previous.status}; "
        f"policy_version={previous.policy_version}; "
        f"evaluated_at={previous.evaluated_at.isoformat() if previous.evaluated_at else 'desconhecido'}; "
        f"reason={previous.reason}"
    )
    current_reason = current.reason or ""
    canonical_eligibility.reason = "\n".join(
        part for part in (current_reason, previous_snapshot) if part
    )
    db.delete(duplicate_eligibility)


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


def list_discovery_jobs(db: Session, *, include_ineligible: bool = False) -> list[Job]:
    """Load only jobs with a current discovery source; legacy imports stay stored."""
    statement = (
        select(Job)
        .join(JobSource, JobSource.job_id == Job.id)
        .where(JobSource.source.in_(("remotive", "jsearch", "jobicy", "fixture")))
        .options(selectinload(Job.sources))
        .distinct()
        .order_by(Job.published_at.desc().nulls_last(), Job.id.desc())
    )
    if not include_ineligible:
        statement = statement.outerjoin(JobEligibility, JobEligibility.job_id == Job.id).where(
            (JobEligibility.status == "eligible") | (JobEligibility.id.is_(None))
        )
    return list(db.scalars(statement).unique().all())


def get_job(db: Session, job_id: int) -> Job | None:
    statement = select(Job).options(selectinload(Job.sources)).where(Job.id == job_id)
    return db.scalar(statement)
