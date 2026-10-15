from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Evidence = Annotated[str, Field(min_length=1, max_length=240)]


class AIAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: Literal["relevant", "maybe", "not_relevant"]
    score: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=1000)
    strengths: list[Evidence] = Field(max_length=8)
    gaps: list[Evidence] = Field(max_length=8)
    unknowns: list[Evidence] = Field(max_length=8)


class AIJobAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    classification: Literal["relevant", "maybe", "not_relevant"]
    score: int = Field(ge=0, le=100)
    rationale: str
    strengths: list[str]
    gaps: list[str]
    unknowns: list[str]
    model: str
    analyzed_at: datetime


class AIAnalysisBatchRead(BaseModel):
    analyzed: int
    remaining: int
    failed: int
    limit: int
