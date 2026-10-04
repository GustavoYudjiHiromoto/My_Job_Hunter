from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.adapters.fixture import FixtureAdapter
from app.db.session import get_db
from app.repositories.jobs import get_job, list_jobs
from app.schemas.jobs import ImportResult, JobRead
from app.services.jobs import import_from_adapter

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobRead])
def read_jobs(db: Session = Depends(get_db)):
    return list_jobs(db)


@router.get("/{job_id}", response_model=JobRead)
def read_job(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")
    return job


@router.post("/import-fixture", response_model=ImportResult)
def import_fixture(db: Session = Depends(get_db)):
    return import_from_adapter(db, FixtureAdapter())
