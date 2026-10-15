from typing import Protocol

from app.schemas.ai_analysis import AIAnalysisResult


class AIJobAnalyzer(Protocol):
    model: str

    def analyze(self, profile: dict, job: dict) -> AIAnalysisResult: ...
