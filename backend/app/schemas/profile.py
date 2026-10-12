from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProfileFields(BaseModel):
    full_name: str = Field(default="", max_length=160)
    email: str = Field(default="", max_length=254)
    professional_summary: str = ""
    resume_text: str = ""
    skills: str = ""
    languages: str = ""


class ProfileUpdate(ProfileFields):
    pass


class ExperienceFields(BaseModel):
    company: str = Field(min_length=1, max_length=160)
    role: str = Field(min_length=1, max_length=160)
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


class ExperienceCreate(ExperienceFields):
    pass


class ExperienceUpdate(ExperienceFields):
    pass


class ExperienceRead(ExperienceFields):
    model_config = ConfigDict(from_attributes=True)
    id: int


class EducationFields(BaseModel):
    institution: str = Field(min_length=1, max_length=160)
    degree: str = Field(min_length=1, max_length=160)
    field_of_study: str = Field(default="", max_length=160)
    start_year: int | None = Field(default=None, ge=1900, le=2200)
    end_year: int | None = Field(default=None, ge=1900, le=2200)

    @model_validator(mode="after")
    def validate_years(self):
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValueError("Ano final deve ser igual ou posterior ao ano inicial.")
        return self


class EducationCreate(EducationFields):
    pass


class EducationUpdate(EducationFields):
    pass


class EducationRead(EducationFields):
    model_config = ConfigDict(from_attributes=True)
    id: int


class PreferenceFields(BaseModel):
    desired_titles: str = ""
    search_keywords: str = ""
    search_areas: str = ""
    desired_locations: str = ""
    work_modes: str = ""
    seniority: str = Field(default="", max_length=80)
    employment_types: str = ""
    minimum_salary: int | None = Field(default=None, ge=0)
    maximum_salary: int | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="BRL", min_length=3, max_length=3)
    must_have: str = ""
    excluded_criteria: str = ""

    @model_validator(mode="after")
    def validate_salary_range(self):
        if (
            self.minimum_salary is not None
            and self.maximum_salary is not None
            and self.maximum_salary < self.minimum_salary
        ):
            raise ValueError("Salário máximo deve ser igual ou superior ao mínimo.")
        return self


class PreferenceUpdate(PreferenceFields):
    pass


class PreferenceRead(PreferenceFields):
    model_config = ConfigDict(from_attributes=True)


class ProfileRead(ProfileFields):
    id: int
    experiences: list[ExperienceRead]
    education: list[EducationRead]
    preference: PreferenceRead | None

    model_config = ConfigDict(from_attributes=True)
