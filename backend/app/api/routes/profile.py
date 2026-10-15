from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Education, Experience
from app.repositories.profile import get_education, get_experience, get_or_create_profile, save_preference
from app.schemas.profile import (
    EducationCreate,
    EducationRead,
    EducationUpdate,
    ExperienceCreate,
    ExperienceRead,
    ExperienceUpdate,
    PreferenceRead,
    PreferenceUpdate,
    ProfileRead,
    ProfileUpdate,
)
from app.services.discovery import reevaluate_discovery_eligibility
from app.services.profile import load_profile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileRead)
def read_profile(db: Session = Depends(get_db)):
    return load_profile(db)


@router.put("", response_model=ProfileRead)
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    for key, value in payload.model_dump().items():
        setattr(profile, key, value)
    db.commit()
    return load_profile(db)


@router.post("/experiences", response_model=ExperienceRead, status_code=status.HTTP_201_CREATED)
def create_experience(payload: ExperienceCreate, db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    item = Experience(profile_id=profile.id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/experiences/{experience_id}", response_model=ExperienceRead)
def update_experience(experience_id: int, payload: ExperienceUpdate, db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    item = get_experience(db, profile.id, experience_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Experiência não encontrada.")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/experiences/{experience_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_experience(experience_id: int, db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    item = get_experience(db, profile.id, experience_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Experiência não encontrada.")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/education", response_model=EducationRead, status_code=status.HTTP_201_CREATED)
def create_education(payload: EducationCreate, db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    item = Education(profile_id=profile.id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/education/{education_id}", response_model=EducationRead)
def update_education(education_id: int, payload: EducationUpdate, db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    item = get_education(db, profile.id, education_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Formação não encontrada.")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/education/{education_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_education(education_id: int, db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    item = get_education(db, profile.id, education_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Formação não encontrada.")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/preferences", response_model=PreferenceRead)
def update_preference(payload: PreferenceUpdate, db: Session = Depends(get_db)):
    profile = get_or_create_profile(db)
    preference = save_preference(db, profile.id, payload.model_dump(), commit=False)
    profile.preference = preference
    reevaluate_discovery_eligibility(db, profile)
    db.commit()
    db.refresh(preference)
    return preference
