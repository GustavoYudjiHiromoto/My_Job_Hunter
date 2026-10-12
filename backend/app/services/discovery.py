import hashlib
import logging
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.adapters.discovery import (
    DiscoveryProviderError,
    JobicyDiscoveryAdapter,
    JSearchDiscoveryAdapter,
    RemotiveDiscoveryAdapter,
    canonical_query_parameters,
)
from app.models import DiscoveryQuery, ImportRun, ImportRunSource, JobDiscovery, JobEligibility, JobSource
from app.models.profile import ProfessionalProfile
from app.repositories.jobs import import_jobs
from app.repositories.profile import get_or_create_profile
from app.services.import_lock import ImportAlreadyRunning, import_lock

logger = logging.getLogger(__name__)
MAX_QUERIES = 4
MAX_JSEARCH_QUERIES = 2
MAX_REMOTIVE_QUERIES = 1
MAX_JOBICY_QUERIES = 1
RESULTS_PER_QUERY = 25
JSEARCH_MONTHLY_REQUEST_LIMIT = 200
JOBICY_COOLDOWN = timedelta(hours=1)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class SearchPlan:
    provider: str
    strategy: str
    terms: list[str]
    parameters: dict[str, Any]
    query_hash: str


def _tokens(value: str | None) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in value.replace(";", "\n").replace(",", "\n").splitlines():
        item = " ".join(raw.split())
        key = " ".join(
            unicodedata.normalize("NFKD", item).encode("ascii", "ignore").decode().casefold().split()
        )
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _query_hash(parameters: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_query_parameters(parameters).encode("utf-8")).hexdigest()


def build_search_plans(profile: ProfessionalProfile) -> list[SearchPlan]:
    """Build deterministic remote searches from explicit profile fields only."""
    preference = profile.preference
    titles = _tokens(preference.desired_titles if preference else "")
    keywords = _tokens(preference.search_keywords if preference else "")
    areas = _tokens(preference.search_areas if preference else "")
    positives = list(dict.fromkeys([*titles, *keywords]))
    if not positives and not areas:
        raise ValueError(
            "Cadastre ao menos um cargo, uma área ou uma palavra-chave antes de descobrir vagas."
        )

    groups = areas or [""]
    plans: list[SearchPlan] = []
    seen_hashes: set[str] = set()
    for area in groups:
        terms = list(dict.fromkeys(([area] if area else []) + positives))[:12]
        parameters = {"search": " ".join(terms), "limit": RESULTS_PER_QUERY}
        query_hash = _query_hash(parameters)
        if query_hash in seen_hashes:
            continue
        seen_hashes.add(query_hash)
        plans.append(
            SearchPlan(
                provider="remotive",
                strategy="remote",
                terms=terms,
                parameters=parameters,
                query_hash=query_hash,
            )
        )
        if len(plans) == MAX_QUERIES:
            break
    return plans


def build_jsearch_search_plans(profile: ProfessionalProfile) -> list[SearchPlan]:
    """Build local and remote plans only from explicit preference fields."""
    preference = profile.preference
    titles = _tokens(preference.desired_titles if preference else "")
    keywords = _tokens(preference.search_keywords if preference else "")
    areas = _tokens(preference.search_areas if preference else "")
    seniority = _tokens(preference.seniority if preference else "")
    employment_types = _tokens(preference.employment_types if preference else "")
    terms = list(dict.fromkeys([*titles, *areas, *keywords, *seniority, *employment_types]))[:8]
    if not terms:
        raise ValueError(
            "Cadastre ao menos um cargo, uma área ou uma palavra-chave antes de descobrir vagas."
        )
    location = next(
        iter(_tokens(preference.desired_locations if preference else "")), "São Paulo"
    )
    strategies = [
        ("location", " ".join([*terms, location]), False),
        ("remote", " ".join([*terms, "remote Brazil"]), True),
    ]
    plans = []
    for strategy, query_text, remote_only in strategies:
        parameters = {
            "query": query_text,
            "country": "br",
            "language": "pt",
            "work_from_home": remote_only,
        }
        plans.append(
            SearchPlan(
                provider="jsearch",
                strategy=strategy,
                terms=query_text.split(),
                parameters=parameters,
                query_hash=_query_hash(parameters),
            )
        )
    return plans


def build_jobicy_search_plans(profile: ProfessionalProfile) -> list[SearchPlan]:
    """Jobicy is remote-only; build one Brazil-scoped tag query from profile fields."""
    preference = profile.preference
    terms = list(dict.fromkeys([
        *_tokens(preference.desired_titles if preference else ""),
        *_tokens(preference.search_keywords if preference else ""),
        *_tokens(preference.search_areas if preference else ""),
        *_tokens(preference.seniority if preference else ""),
        *_tokens(preference.employment_types if preference else ""),
    ]))[:8]
    if not terms:
        return []
    parameters = {"tag": " ".join(terms), "geo": "brazil", "count": RESULTS_PER_QUERY}
    return [SearchPlan(
        provider="jobicy",
        strategy="remote_brazil",
        terms=terms,
        parameters=parameters,
        query_hash=_query_hash(parameters),
    )]


def _jsearch_requests_this_month(db: Session, now: datetime | None = None) -> int:
    current = now or _utc_now()
    month_start = datetime(current.year, current.month, 1, tzinfo=UTC)
    next_month_start = (
        datetime(current.year + 1, 1, 1, tzinfo=UTC)
        if current.month == 12
        else datetime(current.year, current.month + 1, 1, tzinfo=UTC)
    )
    return db.scalar(
        select(func.count(DiscoveryQuery.id))
        .join(ImportRunSource, DiscoveryQuery.import_run_source_id == ImportRunSource.id)
        .join(ImportRun, ImportRunSource.import_run_id == ImportRun.id)
        .where(
            ImportRun.requested_source == "discovery",
            DiscoveryQuery.provider == "jsearch",
            DiscoveryQuery.status.in_(("pending", "succeeded", "failed")),
            DiscoveryQuery.created_at >= month_start,
            DiscoveryQuery.created_at < next_month_start,
        )
    ) or 0


def _jobicy_last_attempt(db: Session) -> datetime | None:
    return db.scalar(
        select(DiscoveryQuery.created_at)
        .join(ImportRunSource, DiscoveryQuery.import_run_source_id == ImportRunSource.id)
        .join(ImportRun, ImportRunSource.import_run_id == ImportRun.id)
        .where(
            ImportRun.requested_source == "discovery",
            DiscoveryQuery.provider == "jobicy",
            DiscoveryQuery.status.in_(("pending", "succeeded", "failed")),
        )
        .order_by(DiscoveryQuery.created_at.desc(), DiscoveryQuery.id.desc())
        .limit(1)
    )


def _jobicy_is_in_cooldown(db: Session, now: datetime | None = None) -> bool:
    last_attempt = _jobicy_last_attempt(db)
    if last_attempt is None:
        return False
    if last_attempt.tzinfo is None:
        last_attempt = last_attempt.replace(tzinfo=UTC)
    return (now or _utc_now()) - last_attempt < JOBICY_COOLDOWN


def prefilter_discovered_job(db: Session, job_id: int) -> JobEligibility:
    """Required pipeline hook; the neutral policy rejects nothing pending approval of rules."""
    result = db.scalar(select(JobEligibility).where(JobEligibility.job_id == job_id))
    if result is None:
        result = JobEligibility(job_id=job_id)
        db.add(result)
    result.status = "eligible"
    result.reason = "Nenhuma regra de pré-filtro configurada; aguardando critérios aprovados."
    result.policy_version = "unconfigured"
    result.evaluated_at = datetime.now(UTC)
    db.flush()
    return result


def _load_run(db: Session, run_id: int) -> ImportRun:
    return db.scalar(
        select(ImportRun).options(selectinload(ImportRun.sources)).where(ImportRun.id == run_id)
    )


def _mark_abandoned_discovery_runs(db: Session) -> None:
    runs = list(
        db.scalars(
            select(ImportRun).where(
                ImportRun.requested_source == "discovery",
                ImportRun.status.in_(("pending", "running")),
            )
        ).all()
    )
    for run in runs:
        run.status = "interrupted"
        run.finished_at = datetime.now(UTC)
        run.error = "A execução anterior terminou antes de registrar o resultado da descoberta."
        for source in run.sources:
            if source.status == "pending":
                source.status = "failed"
                source.error = "A origem não foi concluída porque a execução foi interrompida."
        for source in run.sources:
            for query in source.discovery_queries:
                if query.status == "pending":
                    query.status = "failed"
                    query.error = "A consulta não foi concluída porque a execução foi interrompida."
    if runs:
        db.commit()


def run_discovery(
    db: Session,
    adapter: RemotiveDiscoveryAdapter | None = None,
    jsearch_adapter: JSearchDiscoveryAdapter | None = None,
    jobicy_adapter: JobicyDiscoveryAdapter | None = None,
) -> ImportRun:
    try:
        lock = import_lock(db)
        lock.__enter__()
    except ImportAlreadyRunning:
        now = _utc_now()
        run = ImportRun(
            requested_source="discovery",
            status="skipped",
            started_at=now,
            finished_at=now,
            error="Já existe uma coleta em andamento.",
        )
        db.add(run)
        db.commit()
        return _load_run(db, run.id)

    try:
        _mark_abandoned_discovery_runs(db)
        profile = get_or_create_profile(db)
        try:
            plans = build_search_plans(profile)[:MAX_REMOTIVE_QUERIES]
            plans.extend(build_jsearch_search_plans(profile)[:MAX_JSEARCH_QUERIES])
            plans.extend(build_jobicy_search_plans(profile)[:MAX_JOBICY_QUERIES])
        except ValueError as error:
            raise DiscoveryConfigurationError(str(error)) from error

        run = ImportRun(requested_source="discovery", status="running", started_at=_utc_now())
        db.add(run)
        db.commit()
        providers = {
            "remotive": adapter or RemotiveDiscoveryAdapter(),
            "jsearch": jsearch_adapter or JSearchDiscoveryAdapter(),
            "jobicy": jobicy_adapter or JobicyDiscoveryAdapter(),
        }
        source_scopes = {"remotive": "remote", "jsearch": "br", "jobicy": "brazil"}
        source_runs: dict[str, ImportRunSource] = {}
        any_query_succeeded = False
        any_query_failed = False
        jsearch_blocked_reason: str | None = None

        for plan in plans:
            source_run = source_runs.get(plan.provider)
            if source_run is None:
                source_run = ImportRunSource(
                    import_run_id=run.id,
                    source=plan.provider,
                    scope=source_scopes[plan.provider],
                    status="pending",
                )
                db.add(source_run)
                db.commit()
                source_runs[plan.provider] = source_run
            attempt_at = _utc_now()
            query = DiscoveryQuery(
                import_run_source_id=source_run.id,
                provider=plan.provider,
                strategy=plan.strategy,
                query_hash=plan.query_hash,
                search_terms=" | ".join(plan.terms),
                location=plan.parameters.get("location"),
                parameters=plan.parameters,
                created_at=attempt_at,
            )
            if plan.provider == "jsearch":
                if jsearch_blocked_reason:
                    query.status = "skipped"
                    query.error = jsearch_blocked_reason
                elif not providers[plan.provider].is_configured():
                    query.status = "skipped"
                    query.error = "JSEARCH_API_KEY não configurada; provider opcional ignorado."
                elif _jsearch_requests_this_month(db, now=attempt_at) >= JSEARCH_MONTHLY_REQUEST_LIMIT:
                    query.status = "skipped"
                    query.error = "Limite local mensal de requisições JSearch atingido."
            elif plan.provider == "jobicy" and _jobicy_is_in_cooldown(db, now=attempt_at):
                query.status = "skipped"
                query.error = "Jobicy ignorado: o intervalo mínimo de uma hora ainda não passou."
            db.add(query)
            db.commit()
            if query.status == "skipped":
                continue
            try:
                if plan.provider == "remotive":
                    candidates = providers[plan.provider].search(
                        plan.parameters["search"], limit=RESULTS_PER_QUERY
                    )
                elif plan.provider == "jobicy":
                    candidates = providers[plan.provider].search(
                        plan.parameters["tag"], geo=plan.parameters["geo"], limit=RESULTS_PER_QUERY
                    )
                else:
                    candidates = providers[plan.provider].search(
                        plan.parameters["query"],
                        work_from_home=plan.parameters["work_from_home"],
                        limit=RESULTS_PER_QUERY,
                    )
                candidate_ids: set[int] = set()
                created_ids: set[int] = set()
                created, updated = import_jobs(db, candidates, commit=False, new_job_ids=created_ids)
                for normalized in candidates:
                    source = db.scalar(
                        select(JobSource).where(
                            JobSource.source == normalized.source,
                            JobSource.external_id == normalized.external_id,
                        )
                    )
                    if source is None or source.id in candidate_ids:
                        continue
                    candidate_ids.add(source.id)
                    db.add(JobDiscovery(job_id=source.job_id, job_source_id=source.id, query_id=query.id))
                    prefilter_discovered_job(db, source.job_id)
                query = db.get(DiscoveryQuery, query.id)
                query.status = "succeeded"
                query.created = created
                query.updated = updated
                query.total = len(candidates)
                db.commit()
                any_query_succeeded = True
            except Exception as error:
                db.rollback()
                query = db.get(DiscoveryQuery, query.id)
                query.status = "failed"
                query.error = (
                    str(error)
                    if isinstance(error, (DiscoveryProviderError, ValueError))
                    else f"Falha inesperada na consulta {plan.provider}. Consulte o log do backend."
                )
                if not isinstance(error, (DiscoveryProviderError, ValueError)):
                    logger.exception("Falha inesperada na consulta %s", plan.provider)
                if (
                    plan.provider == "jsearch"
                    and isinstance(error, DiscoveryProviderError)
                    and error.http_status in (401, 403, 429)
                ):
                    jsearch_blocked_reason = (
                        f"JSearch interrompido após HTTP {error.http_status}; "
                        "consultas restantes ignoradas nesta execução."
                    )
                db.commit()
                any_query_failed = True

        for source_run in source_runs.values():
            source_run = db.get(ImportRunSource, source_run.id)
            queries = source_run.discovery_queries
            has_success = any(query.status == "succeeded" for query in queries)
            has_failure = any(query.status == "failed" for query in queries)
            has_skip = any(query.status == "skipped" for query in queries)
            source_run.status = "succeeded" if has_success else "failed" if has_failure else "skipped"
            source_run.created = sum(query.created for query in queries)
            source_run.updated = sum(query.updated for query in queries)
            source_run.total = sum(query.total for query in queries)
            if has_failure:
                errors = [query.error for query in queries if query.error]
                source_run.error = (
                    f"Uma ou mais consultas {source_run.source} falharam: " + "; ".join(errors)
                )
            elif has_skip:
                source_run.error = "; ".join(query.error for query in queries if query.error)
        run = db.get(ImportRun, run.id)
        run.created = sum(source.created for source in source_runs.values())
        run.updated = sum(source.updated for source in source_runs.values())
        run.total = sum(source.total for source in source_runs.values())
        run.status = (
            "partial" if any_query_succeeded and any_query_failed
            else "succeeded" if any_query_succeeded
            else "failed"
        )
        if any_query_failed:
            run.error = "Uma ou mais consultas de descoberta falharam; consulte o resultado das origens."
        run.finished_at = _utc_now()
        db.commit()
        return _load_run(db, run.id)
    finally:
        lock.__exit__(None, None, None)


class DiscoveryConfigurationError(ValueError):
    """Perfil ainda não tem dados suficientes para criar consultas remotas."""


def latest_discovery_run(db: Session) -> ImportRun | None:
    return db.scalar(
        select(ImportRun)
        .options(selectinload(ImportRun.sources).selectinload(ImportRunSource.discovery_queries))
        .where(ImportRun.requested_source == "discovery")
        .order_by(ImportRun.started_at.desc(), ImportRun.id.desc())
        .limit(1)
    )
