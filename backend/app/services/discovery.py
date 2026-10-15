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
from app.models import (
    DiscoveryQuery,
    ImportRun,
    ImportRunSource,
    Job,
    JobDiscovery,
    JobEligibility,
    JobSource,
)
from app.models.profile import ProfessionalProfile
from app.repositories.jobs import import_jobs
from app.repositories.profile import get_or_create_profile
from app.services.import_lock import ImportAlreadyRunning, import_lock

logger = logging.getLogger(__name__)
MAX_JSEARCH_QUERIES = 2
MAX_REMOTIVE_QUERIES = 1
MAX_JOBICY_QUERIES = 1
JSEARCH_RESULTS_PER_QUERY = 25
JOBICY_RESULTS_PER_QUERY = 200
JOBICY_TAG_MAX_BYTES = 50
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


def _jobicy_tag(terms: list[str]) -> str:
    """Build a deterministic keyword accepted by Jobicy's 50-byte tag limit."""
    result = ""
    for word in " ".join(terms).split():
        candidate = f"{result} {word}".strip()
        if len(candidate.encode("utf-8")) <= JOBICY_TAG_MAX_BYTES:
            result = candidate
            continue
        if not result:
            # Keep a valid UTF-8 prefix if one unusually long token is supplied.
            for character in word:
                candidate = result + character
                if len(candidate.encode("utf-8")) > JOBICY_TAG_MAX_BYTES:
                    break
                result = candidate
        break
    return result


def build_search_plans(profile: ProfessionalProfile) -> list[SearchPlan]:
    """Fetch Remotive's complete active remote-jobs feed in one request."""
    parameters: dict[str, Any] = {}
    return [
        SearchPlan(
            provider="remotive",
            strategy="all_active_remote",
            terms=[],
            parameters=parameters,
            query_hash=_query_hash(parameters),
        )
    ]


def build_jsearch_search_plans(profile: ProfessionalProfile) -> list[SearchPlan]:
    """Build local and remote plans only from explicit preference fields."""
    preference = profile.preference
    titles = _tokens(preference.desired_titles if preference else "")
    keywords = _tokens(preference.search_keywords if preference else "")
    areas = _tokens(preference.search_areas if preference else "")
    primary_role = next(iter(titles or keywords or areas), None)
    if not primary_role:
        raise ValueError(
            "Cadastre ao menos um cargo, uma área ou uma palavra-chave antes de descobrir vagas."
        )
    location = next(
        iter(_tokens(preference.desired_locations if preference else "")), "São Paulo"
    )
    strategies = [
        ("location", f"{primary_role} in {location}", False),
        ("remote", f"{primary_role} remote Brazil", True),
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
    tag = _jobicy_tag(terms)
    if len(tag.encode("utf-8")) < 3:
        return []
    parameters = {"tag": tag, "geo": "brazil", "count": JOBICY_RESULTS_PER_QUERY}
    return [SearchPlan(
        provider="jobicy",
        strategy="remote_brazil",
        terms=tag.split(),
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


def prefilter_discovered_job(
    db: Session, job_id: int, profile: ProfessionalProfile | None = None
) -> JobEligibility:
    """Apply deterministic profile rules while retaining every collected job."""
    result = db.scalar(select(JobEligibility).where(JobEligibility.job_id == job_id))
    if result is None:
        result = JobEligibility(job_id=job_id)
        db.add(result)
    profile = profile or get_or_create_profile(db)
    preference = profile.preference
    reasons: list[str] = []
    needs_review: list[str] = []

    sources = list(db.scalars(select(JobSource).where(JobSource.job_id == job_id)).all())
    job_record = db.get(Job, job_id)
    if job_record is None:
        return result
    source_payloads = [source.original_payload for source in sources]
    remote = (job_record.workplace_type or "").casefold() in {"remote", "remoto", "remota"}
    remote = remote or any(source.source in {"remotive", "jobicy"} for source in sources)
    remote = remote or any(
        payload.get("job_is_remote") is True
        for payload in source_payloads
        if isinstance(payload, dict)
    )
    modes = _tokens(preference.work_modes if preference else "")
    remote_allowed = any(
        unicodedata.normalize("NFKD", mode).encode("ascii", "ignore").decode().casefold()
        in {"remote", "remoto", "remota", "indiferente", "qualquer"}
        for mode in modes
    )
    if remote:
        if not remote_allowed:
            reasons.append("Vaga remota, mas a modalidade remota não está habilitada nas preferências.")
    else:
        location = job_record.location or ""
        normalized_location = _search_normalize(location)
        preferred_locations = _tokens(preference.desired_locations if preference else "") or ["São Paulo"]
        if not location.strip():
            needs_review.append("Localização ausente; não foi possível confirmar São Paulo.")
        elif not any(_search_normalize(term) in normalized_location for term in preferred_locations):
            reasons.append("Localização fora das cidades configuradas (padrão: São Paulo).")

    area_terms = _tokens(preference.search_areas if preference else "")
    if area_terms:
        search_text_parts = [job_record.title, job_record.description]
        area_metadata_present = bool(job_record.description.strip())
        for payload in source_payloads:
            if not isinstance(payload, dict):
                continue
            for key in ("department", "category", "job_category", "job_function", "department_name"):
                value = payload.get(key)
                if isinstance(value, str):
                    search_text_parts.append(value)
                    area_metadata_present = area_metadata_present or bool(value.strip())
        search_text = _search_normalize(" ".join(search_text_parts))
        area_aliases = {
            "ti": (
                "ti", "it", "technology", "tecnologia", "software", "developer",
                "desenvolvimento", "backend", "frontend", "infraestrutura", "sistemas",
            ),
            "tecnologia da informacao": (
                "tecnologia", "software", "developer", "desenvolvimento", "backend",
                "frontend", "infraestrutura", "sistemas",
            ),
            "software": (
                "software", "developer", "desenvolvimento", "backend", "frontend",
                "full stack", "engineering", "engenharia",
            ),
            "dados": (
                "data", "dados", "analytics", "analise", "bi", "business intelligence",
                "machine learning", "cientista de dados",
            ),
        }
        matched_areas = []
        for term in area_terms:
            normalized_term = _search_normalize(term)
            candidates = area_aliases.get(normalized_term, (normalized_term,))
            if any(_search_contains(search_text, candidate) for candidate in candidates):
                matched_areas.append(term)
        if not matched_areas:
            if area_metadata_present:
                reasons.append("Área profissional não corresponde às áreas configuradas.")
            else:
                needs_review.append("Dados de área ausentes; revisar manualmente.")

    excluded_terms = _tokens(preference.excluded_criteria if preference else "")
    exclusion_text = _search_normalize(" ".join(
        [job_record.title, job_record.description, job_record.location or ""]
    ))
    matched_exclusions = [term for term in excluded_terms if _search_contains(exclusion_text, term)]
    if matched_exclusions:
        reasons.append("Critério de exclusão encontrado: " + ", ".join(matched_exclusions) + ".")

    result.status = "rejected" if reasons else "needs_review" if needs_review else "eligible"
    result.reason = "; ".join(reasons or needs_review) or (
        "Compatível com as regras obrigatórias configuradas."
    )
    result.policy_version = "profile-v1"
    result.evaluated_at = datetime.now(UTC)
    db.flush()
    return result


def reevaluate_discovery_eligibility(db: Session, profile: ProfessionalProfile) -> None:
    """Keep persisted eligibility aligned with edits to the current preferences."""
    job_ids = list(
        db.scalars(
            select(Job.id)
            .join(JobSource, JobSource.job_id == Job.id)
            .where(JobSource.source.in_(("remotive", "jsearch", "jobicy")))
            .distinct()
        ).all()
    )
    for job_id in job_ids:
        prefilter_discovered_job(db, job_id, profile)


def _search_normalize(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold().split()
    )


def _search_contains(text: str, term: str) -> bool:
    normalized_term = _search_normalize(term)
    return bool(normalized_term) and f" {normalized_term} " in f" {text} "


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
                        plan.parameters.get("search"), limit=plan.parameters.get("limit")
                    )
                elif plan.provider == "jobicy":
                    candidates = providers[plan.provider].search(
                        plan.parameters["tag"],
                        geo=plan.parameters["geo"],
                        limit=plan.parameters["count"],
                    )
                else:
                    candidates = providers[plan.provider].search(
                        plan.parameters["query"],
                        work_from_home=plan.parameters["work_from_home"],
                        limit=JSEARCH_RESULTS_PER_QUERY,
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
                    prefilter_discovered_job(db, source.job_id, profile)
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
