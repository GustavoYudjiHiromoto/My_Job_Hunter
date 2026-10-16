from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_ai_api_key, get_ai_model
from app.db.session import get_db
from app.models import Education, Experience, ProfessionalProfile
from app.providers.ai.openrouter import AIProviderError
from app.providers.ai.openrouter_resume import OpenRouterResumeParser
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
from app.schemas.resume_import import ResumeImportApply, ResumeImportApplyRead, ResumeImportDraft
from app.services.discovery import reevaluate_discovery_eligibility
from app.services.profile import load_profile
from app.services.resume_import import MAX_PDF_BYTES, ResumeImportError, extract_resume_text

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


@router.post("/resume-import/preview", response_model=ResumeImportDraft)
def preview_resume_import(
    file: UploadFile = File(...),
    consent_to_openrouter: bool = Form(...),
):
    if not consent_to_openrouter:
        raise HTTPException(
            status_code=400,
            detail="É necessário autorizar o envio do texto extraído ao OpenRouter.",
        )
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Envie um arquivo PDF.")
    pdf_bytes = file.file.read(MAX_PDF_BYTES + 1)
    try:
        resume_text = extract_resume_text(pdf_bytes)
    except ResumeImportError as error:
        messages = {
            "pdf_too_large": "O PDF deve ter no máximo 8 MB.",
            "encrypted_pdf": "O PDF está protegido por senha.",
            "too_many_pages": "O PDF deve ter no máximo 40 páginas.",
            "no_extractable_text": (
                "Não foi possível extrair texto. PDFs digitalizados/OCR não são suportados."
            ),
            "resume_text_too_long": "O texto extraído excede o limite de processamento.",
        }
        raise HTTPException(
            status_code=400,
            detail=messages.get(error.code, "Não foi possível ler este PDF."),
        ) from error
    api_key = get_ai_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Configure OPENROUTER_API_KEY no backend para importar o currículo.",
        )
    try:
        parsed = OpenRouterResumeParser(api_key, get_ai_model()).parse(resume_text)
    except AIProviderError as error:
        raise HTTPException(
            status_code=502,
            detail="Não foi possível analisar o currículo com o provider de IA.",
        ) from error
    return parsed.model_copy(update={"resume_text": resume_text})


@router.put("/resume-import/apply", response_model=ResumeImportApplyRead)
def apply_resume_import(payload: ResumeImportApply, db: Session = Depends(get_db)):
    profile = db.get(ProfessionalProfile, 1)
    if profile is None:
        profile = ProfessionalProfile(id=1)
        db.add(profile)

    added_experiences = 0
    added_education = 0
    saved_sections = []
    try:
        for field in ("professional_summary", "skills", "languages", "resume_text"):
            value = getattr(payload.draft, field)
            if field in payload.sections and value.strip():
                setattr(profile, field, value)
                saved_sections.append(field)

        if "experiences" in payload.sections:
            existing = {
                _record_key(item.company, item.role, item.start_date)
                for item in db.scalars(select(Experience).where(Experience.profile_id == profile.id))
            }
            for item in payload.draft.experiences:
                if not item.company.strip() or not item.role.strip():
                    continue
                key = _record_key(item.company, item.role, item.start_date)
                if key not in existing:
                    db.add(Experience(profile_id=profile.id, **item.model_dump()))
                    existing.add(key)
                    added_experiences += 1
            if added_experiences:
                saved_sections.append("experiences")

        if "education" in payload.sections:
            existing = {
                _record_key(item.institution, item.degree, item.start_year)
                for item in db.scalars(select(Education).where(Education.profile_id == profile.id))
            }
            for item in payload.draft.education:
                if not item.institution.strip() or not item.degree.strip():
                    continue
                key = _record_key(item.institution, item.degree, item.start_year)
                if key not in existing:
                    db.add(Education(profile_id=profile.id, **item.model_dump()))
                    existing.add(key)
                    added_education += 1
            if added_education:
                saved_sections.append("education")

        db.commit()
    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Não foi possível salvar a importação do currículo.",
        ) from error

    return ResumeImportApplyRead(
        saved_sections=sorted(saved_sections),
        experiences_added=added_experiences,
        education_added=added_education,
    )


def _record_key(*values) -> tuple[str, ...]:
    return tuple(str(value or "").strip().casefold() for value in values)


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
