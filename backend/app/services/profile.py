from sqlalchemy.orm import Session

from app.models import ProfessionalProfile
from app.repositories.profile import get_or_create_profile


def load_profile(db: Session) -> ProfessionalProfile:
    profile = get_or_create_profile(db)
    db.refresh(profile)
    return profile
