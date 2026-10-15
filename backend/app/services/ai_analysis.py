import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_openai_api_key, get_openai_model
from app.models import AIJobAnalysis, Job, ProfessionalProfile
from app.providers.ai.base import AIJobAnalyzer
from app.providers.ai.openai import AIProviderError, OpenAIJobAnalyzer
from app.repositories.jobs import list_discovery_jobs
from app.repositories.profile import get_or_create_profile
from app.schemas.ai_analysis import AIAnalysisBatchRead

ANALYSIS_BATCH_LIMIT = 10
PROMPT_VERSION = "job-relevance-v1"
DISCOVERY_SOURCES = {"remotive", "jsearch", "jobicy"}


class AIAnalysisConfigurationError(RuntimeError):
    pass


def _analysis_inputs(profile: ProfessionalProfile, job: Job) -> tuple[dict, dict]:
    def clipped(value: str | None, maximum: int) -> str:
        return (value or "")[:maximum]

    preference = profile.preference
    preference_data = {}
    if preference:
        preference_data = {
            key: clipped(getattr(preference, key), 500)
            for key in (
                "desired_titles", "search_keywords", "search_areas", "desired_locations",
                "work_modes", "seniority", "employment_types", "salary_currency",
                "must_have", "excluded_criteria",
            )
        }
        preference_data.update(
            minimum_salary=preference.minimum_salary,
            maximum_salary=preference.maximum_salary,
        )
    profile_data = {
        "skills": clipped(profile.skills, 3000),
        "experience_roles": [clipped(item.role, 160) for item in profile.experiences[:15] if item.role],
        "education": [
            {"degree": clipped(item.degree, 160), "field_of_study": clipped(item.field_of_study, 160)}
            for item in profile.education[:10]
        ],
        "preferences": preference_data,
    }
    job_data = {
        "title": job.title,
        "description": job.description[:10000],
        "location": job.location,
        "workplace_type": job.workplace_type,
        "seniority": job.seniority,
        "employment_type": job.employment_type,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
    }
    return profile_data, job_data


def analysis_request_hash(profile_data: dict, job_data: dict, model: str) -> str:
    canonical = json.dumps(
        {
            "profile": profile_data,
            "job": job_data,
            "model": model,
            "prompt_version": PROMPT_VERSION,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def current_analysis_hash(profile: ProfessionalProfile, job: Job, model: str) -> str:
    profile_data, job_data = _analysis_inputs(profile, job)
    return analysis_request_hash(profile_data, job_data, model)


def run_next_ai_analysis(
    db: Session,
    *,
    analyzer: AIJobAnalyzer | None = None,
    limit: int = ANALYSIS_BATCH_LIMIT,
) -> AIAnalysisBatchRead:
    profile = get_or_create_profile(db)
    model = analyzer.model if analyzer else get_openai_model()
    jobs = [
        job for job in list_discovery_jobs(db, include_ineligible=True)
        if job.status == "open"
        if any(source.source in DISCOVERY_SOURCES for source in job.sources)
    ]
    analyses = {
        item.job_id: item
        for item in db.scalars(
            select(AIJobAnalysis).where(AIJobAnalysis.job_id.in_([job.id for job in jobs]))
        ).all()
    } if jobs else {}
    pending: list[tuple[Job, dict, dict, str]] = []
    for job in jobs:
        profile_data, job_data = _analysis_inputs(profile, job)
        request_hash = analysis_request_hash(profile_data, job_data, model)
        if analyses.get(job.id) and analyses[job.id].request_hash == request_hash:
            continue
        pending.append((job, profile_data, job_data, request_hash))

    if not pending:
        return AIAnalysisBatchRead(analyzed=0, remaining=0, failed=0, limit=limit)
    if analyzer is None:
        api_key = get_openai_api_key()
        if not api_key:
            raise AIAnalysisConfigurationError("Configure OPENAI_API_KEY no ambiente do backend.")
        analyzer = OpenAIJobAnalyzer(api_key=api_key, model=model)

    analyzed = 0
    failed = 0
    for job, profile_data, job_data, request_hash in pending[:limit]:
        try:
            result = analyzer.analyze(profile_data, job_data)
        except AIProviderError:
            failed += 1
            continue
        record = analyses.get(job.id)
        if record is None:
            record = AIJobAnalysis(job_id=job.id)
            db.add(record)
            analyses[job.id] = record
        record.request_hash = request_hash
        record.model = model
        record.prompt_version = PROMPT_VERSION
        record.classification = result.classification
        record.score = result.score
        record.rationale = result.rationale
        record.strengths = result.strengths
        record.gaps = result.gaps
        record.unknowns = result.unknowns
        analyzed += 1

    db.commit()
    remaining = max(0, len(pending) - min(limit, len(pending)) + failed)
    return AIAnalysisBatchRead(analyzed=analyzed, remaining=remaining, failed=failed, limit=limit)
