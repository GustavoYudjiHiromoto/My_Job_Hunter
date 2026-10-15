from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.fixture import FixtureAdapter
from app.core.config import get_greenhouse_board_tokens, get_lever_region, get_lever_sites, get_openai_model
from app.db.session import get_db
from app.models import AIJobAnalysis, JobEligibility
from app.repositories.jobs import get_job, list_discovery_jobs, list_jobs
from app.repositories.profile import get_or_create_profile
from app.schemas.ai_analysis import AIAnalysisBatchRead
from app.schemas.jobs import (
    GreenhouseImportResult,
    ImportResult,
    ImportRunRead,
    JobRead,
    JobRecommendation,
    LeverImportResult,
)
from app.services.ai_analysis import (
    AIAnalysisConfigurationError,
    current_analysis_hash,
    run_next_ai_analysis,
)
from app.services.discovery import (
    DiscoveryConfigurationError,
    latest_discovery_run,
    run_discovery,
)
from app.services.jobs import import_from_adapter, latest_import_run, run_import
from app.services.matching import rank_jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobRead])
def read_jobs(db: Session = Depends(get_db)):
    return list_jobs(db)


@router.get("/recommendations", response_model=list[JobRecommendation])
def read_recommendations(
    min_score: int = Query(default=0, ge=0, le=100),
    location: str | None = Query(default=None, min_length=1, max_length=200),
    workplace_type: str | None = Query(default=None, min_length=1, max_length=40),
    status: Literal["open", "closed", "all"] = "open",
    include_excluded: bool = True,
    include_ineligible: bool = False,
    db: Session = Depends(get_db),
):
    profile = get_or_create_profile(db)
    recommendations = rank_jobs(
        list_discovery_jobs(db, include_ineligible=include_ineligible),
        profile,
        min_score=min_score,
        location=location,
        workplace_type=workplace_type,
        status=status,
        include_excluded=include_excluded,
    )
    eligibility = {
        item.job_id: item
        for item in db.scalars(
            select(JobEligibility).where(
                JobEligibility.job_id.in_([item.job.id for item in recommendations])
            )
        ).all()
    } if recommendations else {}
    ai_analyses = {
        item.job_id: item
        for item in db.scalars(
            select(AIJobAnalysis).where(
                AIJobAnalysis.job_id.in_([item.job.id for item in recommendations])
            )
        ).all()
    } if recommendations else {}
    response = []
    for item in recommendations:
        updates = {}
        if item.job.id in eligibility:
            updates.update(
                eligibility_status=eligibility[item.job.id].status,
                eligibility_reason=eligibility[item.job.id].reason,
            )
        analysis = ai_analyses.get(item.job.id)
        if (
            analysis is not None
            and analysis.model == get_openai_model()
            and analysis.request_hash == current_analysis_hash(profile, item.job, analysis.model)
        ):
            updates["ai_analysis"] = analysis
        response.append(item.model_copy(update=updates) if updates else item)
    return response


@router.get("/import-runs/latest", response_model=ImportRunRead | None)
def read_latest_import_run(db: Session = Depends(get_db)):
    return latest_import_run(db)


@router.get("/discovery-runs/latest", response_model=ImportRunRead | None)
def read_latest_discovery_run(db: Session = Depends(get_db)):
    return latest_discovery_run(db)


@router.post("/discover", response_model=ImportRunRead)
def discover_remote_jobs(db: Session = Depends(get_db)):
    try:
        run = run_discovery(db)
    except DiscoveryConfigurationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if run.status == "skipped":
        raise HTTPException(status_code=409, detail=run.error)
    return run


@router.post("/ai-analysis", response_model=AIAnalysisBatchRead)
def analyze_discovered_jobs_with_ai(db: Session = Depends(get_db)):
    """Analyze up to ten stored discovery jobs on explicit user request."""
    try:
        return run_next_ai_analysis(db)
    except AIAnalysisConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/{job_id}", response_model=JobRead)
def read_job(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")
    return job


@router.post("/import-fixture", response_model=ImportResult)
def import_fixture(db: Session = Depends(get_db)):
    return import_from_adapter(db, FixtureAdapter())


@router.post("/import-greenhouse", response_model=GreenhouseImportResult)
def import_greenhouse(db: Session = Depends(get_db)):
    board_tokens = get_greenhouse_board_tokens()
    if not board_tokens:
        raise HTTPException(
            status_code=503,
            detail="Configure GREENHOUSE_BOARDS com um ou mais tokens públicos de board.",
        )
    run = run_import(db, "greenhouse", greenhouse_tokens=board_tokens)
    if run.status == "skipped":
        raise HTTPException(status_code=409, detail=run.error)
    sources = [item for item in run.sources if item.source == "greenhouse"]
    return GreenhouseImportResult(
        boards_configured=len(sources),
        boards_succeeded=sum(item.status == "succeeded" for item in sources),
        created=sum(item.created for item in sources),
        updated=sum(item.updated for item in sources),
        total=sum(item.total for item in sources),
        errors=[{"board_token": item.scope, "message": item.error} for item in sources if item.error],
    )


@router.post("/import-lever", response_model=LeverImportResult)
def import_lever(db: Session = Depends(get_db)):
    sites = get_lever_sites()
    if not sites:
        raise HTTPException(
            status_code=503,
            detail="Configure LEVER_SITES com um ou mais identificadores públicos de site.",
        )
    region = get_lever_region()
    if region not in {"global", "eu"}:
        raise HTTPException(status_code=503, detail="Configure LEVER_REGION como 'global' ou 'eu'.")
    run = run_import(db, "lever", lever_sites=sites, lever_region=region)
    if run.status == "skipped":
        raise HTTPException(status_code=409, detail=run.error)
    sources = [item for item in run.sources if item.source == "lever"]
    return LeverImportResult(
        sites_configured=len(sources),
        sites_succeeded=sum(item.status == "succeeded" for item in sources),
        created=sum(item.created for item in sources),
        updated=sum(item.updated for item in sources),
        total=sum(item.total for item in sources),
        errors=[{"site": item.scope, "message": item.error} for item in sources if item.error],
    )
