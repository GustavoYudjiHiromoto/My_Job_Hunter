from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Education, Experience, Preference, ProfessionalProfile


def get_or_create_profile(db: Session) -> ProfessionalProfile:
    profile = db.get(ProfessionalProfile, 1)
    if profile is None:
        profile = ProfessionalProfile(id=1)
        db.add(profile)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            profile = db.get(ProfessionalProfile, 1)
            if profile is None:
                raise
        else:
            db.refresh(profile)
    return profile


def get_experience(db: Session, profile_id: int, experience_id: int) -> Experience | None:
    return db.scalar(
        select(Experience).where(Experience.id == experience_id, Experience.profile_id == profile_id)
    )


def get_education(db: Session, profile_id: int, education_id: int) -> Education | None:
    return db.scalar(
        select(Education).where(Education.id == education_id, Education.profile_id == profile_id)
    )


def save_preference(db: Session, profile_id: int, fields: dict, *, commit: bool = True) -> Preference:
    preference = db.scalar(select(Preference).where(Preference.profile_id == profile_id))
    if preference is None:
        preference = Preference(profile_id=profile_id, **fields)
        db.add(preference)
    else:
        for key, value in fields.items():
            setattr(preference, key, value)
    db.flush()
    if commit:
        db.commit()
        db.refresh(preference)
    return preference
