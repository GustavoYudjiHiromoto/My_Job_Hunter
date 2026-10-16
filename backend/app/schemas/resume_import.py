from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResumeExperienceDraft(BaseModel):
    company: str = Field(max_length=160)
    role: str = Field(max_length=160)
    location: str = Field(default="", max_length=160)
    description: str = ""
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False

    @model_validator(mode="after")
    def validate_dates(self):
        if self.is_current and self.end_date is not None:
            raise ValueError("Experiência atual não pode ter data final.")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("Data final deve ser igual ou posterior à data inicial.")
        return self


class ResumeEducationDraft(BaseModel):
    institution: str = Field(max_length=160)
    degree: str = Field(max_length=160)
    field_of_study: str = Field(default="", max_length=160)
    start_year: int | None = Field(default=None, ge=1900, le=2200)
    end_year: int | None = Field(default=None, ge=1900, le=2200)

    @model_validator(mode="after")
    def validate_years(self):
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValueError("Ano final deve ser igual ou posterior ao ano inicial.")
        return self


class ResumeImportDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    professional_summary: str = ""
    skills: str = ""
    languages: str = ""
    experiences: list[ResumeExperienceDraft] = Field(default_factory=list, max_length=30)
    education: list[ResumeEducationDraft] = Field(default_factory=list, max_length=20)
    resume_text: str = ""


class ResumeExperienceAI(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    role: str
    location: str
    description: str
    start_date: date | None
    end_date: date | None
    is_current: bool


class ResumeEducationAI(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institution: str
    degree: str
    field_of_study: str
    start_year: int | None
    end_year: int | None


class ResumeAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    professional_summary: str
    skills: str
    languages: str
    experiences: list[ResumeExperienceAI]
    education: list[ResumeEducationAI]


class ResumeImportApply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: set[
        Literal["professional_summary", "skills", "languages", "resume_text", "experiences", "education"]
    ] = Field(min_length=1)
    draft: ResumeImportDraft


class ResumeImportApplyRead(BaseModel):
    saved_sections: list[str]
    experiences_added: int
    education_added: int
