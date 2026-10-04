from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class NormalizedJob(BaseModel):
    source: str = Field(min_length=1, max_length=80)
    external_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    description: str = ""
    location: str | None = Field(default=None, max_length=200)
    workplace_type: str | None = Field(default=None, max_length=40)
    seniority: str | None = Field(default=None, max_length=80)
    employment_type: str | None = Field(default=None, max_length=80)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    published_at: datetime | None = None
    status: Literal["open", "closed", "unknown"] = "open"
    source_url: HttpUrl
    original_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_salary_range(self):
        if self.salary_min is not None and self.salary_max is not None and self.salary_max < self.salary_min:
            raise ValueError("Salário máximo deve ser igual ou superior ao mínimo.")
        return self


class JobSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source: str
    external_id: str
    source_url: str
    collected_at: datetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    company: str
    description: str
    location: str | None
    workplace_type: str | None
    seniority: str | None
    employment_type: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    published_at: datetime | None
    status: str
    created_at: datetime
    sources: list[JobSourceRead]


class ImportResult(BaseModel):
    source: str
    created: int
    updated: int
    total: int
