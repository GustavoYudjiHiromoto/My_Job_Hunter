import json

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AIJobAnalysis, Job, JobSource
from app.providers.ai.openai import AIProviderError, OpenAIJobAnalyzer
from app.schemas.ai_analysis import AIAnalysisResult
from app.schemas.jobs import NormalizedJob


def _add_discovery_jobs(count: int) -> None:
    with Session(_test_engine()) as db:
        db.add_all(
            Job(
                title=f"Backend Developer {index}",
                company="Example",
                description="Python APIs and SQL.",
                location="São Paulo",
                status="open",
                sources=[JobSource(
                    source="remotive",
                    external_id=f"remotive-{index}",
                    source_url=f"https://example.test/jobs/{index}",
                    original_payload={},
                )],
            )
            for index in range(count)
        )
        db.commit()


def _test_engine():
    # Resolve the fixture's temporary engine only after it patches app.main.engine.
    from app.main import engine

    return engine


class _FakeAnalyzer:
    model = "fake-model"

    def __init__(self, fail_once: bool = False):
        self.calls = []
        self.fail_once = fail_once

    def analyze(self, profile: dict, job: dict) -> AIAnalysisResult:
        self.calls.append((profile, job))
        if self.fail_once:
            self.fail_once = False
            raise AIProviderError("sensitive provider details must not escape")
        return AIAnalysisResult(
            classification="relevant",
            score=87,
            rationale="Competências principais aparecem nos requisitos.",
            strengths=["Python"],
            gaps=["Experiência com cloud não confirmada"],
            unknowns=["Faixa salarial não informada"],
        )


def test_manual_analysis_batches_ten_caches_results_and_omits_profile_pii(client, monkeypatch):
    from app.services import ai_analysis

    monkeypatch.setattr(ai_analysis, "get_openai_api_key", lambda: "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "fake-model")
    analyzer = _FakeAnalyzer()
    monkeypatch.setattr(ai_analysis, "OpenAIJobAnalyzer", lambda api_key, model: analyzer)
    _add_discovery_jobs(12)

    first = client.post("/api/jobs/ai-analysis")

    assert first.status_code == 200
    assert first.json() == {"analyzed": 10, "remaining": 2, "failed": 0, "limit": 10}
    assert len(analyzer.calls) == 10
    sent_profile, sent_job = analyzer.calls[0]
    assert not {"full_name", "email", "resume_text", "professional_summary"}.intersection(sent_profile)
    assert "source_url" not in sent_job
    assert "description" in sent_job
    with Session(_test_engine()) as db:
        assert db.scalar(select(func.count(AIJobAnalysis.id))) == 10

    second = client.post("/api/jobs/ai-analysis")
    third = client.post("/api/jobs/ai-analysis")
    assert second.json()["analyzed"] == 2
    assert second.json()["remaining"] == 0
    assert third.json()["analyzed"] == 0
    assert len(analyzer.calls) == 12

    recommendations = client.get("/api/jobs/recommendations").json()
    analyzed = next(item for item in recommendations if item["ai_analysis"] is not None)
    assert analyzed["ai_analysis"]["classification"] == "relevant"
    assert analyzed["score"] == 0  # AI result is not substituted for deterministic score.


def test_partial_provider_failure_does_not_discard_successful_assessments(client, monkeypatch):
    from app.services import ai_analysis

    monkeypatch.setattr(ai_analysis, "get_openai_api_key", lambda: "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "fake-model")
    analyzer = _FakeAnalyzer(fail_once=True)
    monkeypatch.setattr(ai_analysis, "OpenAIJobAnalyzer", lambda api_key, model: analyzer)
    _add_discovery_jobs(2)

    response = client.post("/api/jobs/ai-analysis")

    assert response.status_code == 200
    assert response.json() == {"analyzed": 1, "remaining": 1, "failed": 1, "limit": 10}
    assert len(analyzer.calls) == 2
    with Session(_test_engine()) as db:
        assert db.scalar(select(func.count(AIJobAnalysis.id))) == 1
    assert "sensitive provider details" not in response.text


def test_missing_openai_key_is_reported_without_provider_call(client, monkeypatch):
    from app.services import ai_analysis

    monkeypatch.setattr(ai_analysis, "get_openai_api_key", lambda: "")
    _add_discovery_jobs(1)

    response = client.post("/api/jobs/ai-analysis")

    assert response.status_code == 503
    assert response.json()["detail"] == "Configure OPENAI_API_KEY no ambiente do backend."
    with Session(_test_engine()) as db:
        assert db.scalar(select(func.count(AIJobAnalysis.id))) == 0


def test_openai_provider_parses_structured_output_without_leaking_http_errors(monkeypatch):
    expected = {
        "classification": "maybe",
        "score": 62,
        "rationale": "Há correspondência parcial.",
        "strengths": ["Python"],
        "gaps": [],
        "unknowns": [],
    }
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(expected)},
        ]}]})

    httpx_client = httpx.Client
    monkeypatch.setattr(
        "app.providers.ai.openai.httpx.Client",
        lambda **kwargs: httpx_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = OpenAIJobAnalyzer("unit-test-key", "fake-model").analyze({"skills": "Python"}, {"title": "Dev"})

    assert result.classification == "maybe"
    assert requests[0].url == "https://api.openai.com/v1/responses"
    assert requests[0].headers["authorization"] == "Bearer unit-test-key"
    request_payload = json.loads(requests[0].content)
    assert request_payload["store"] is False
    assert request_payload["text"]["format"]["type"] == "json_schema"


def test_openai_provider_wraps_http_error_without_response_body_or_key(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "private response body"}})

    httpx_client = httpx.Client
    monkeypatch.setattr(
        "app.providers.ai.openai.httpx.Client",
        lambda **kwargs: httpx_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    api_key = "unit-test-secret"
    with pytest.raises(AIProviderError) as error:
        OpenAIJobAnalyzer(api_key, "fake-model").analyze(
            {"skills": "secret profile"}, {"title": "private job"}
        )

    assert str(error.value) == "analysis_unavailable"
    assert api_key not in str(error.value)
    assert "private response body" not in str(error.value)
    assert "secret profile" not in str(error.value)
    assert "private job" not in str(error.value)


@pytest.mark.parametrize("canonical_has_analysis", [False, True])
def test_job_deduplication_keeps_ai_analysis_on_canonical_job(client, canonical_has_analysis):
    from app.repositories.jobs import import_jobs

    with Session(_test_engine()) as db:
        canonical = Job(
            title="Backend Engineer", company="Example", location="São Paulo", status="open",
            sources=[JobSource(source="greenhouse", external_id="acme:canonical",
                               source_url="https://example.test/canonical", original_payload={})],
        )
        duplicate = Job(
            title="BACKEND ENGINEER", company="Example", location="Sao Paulo", status="open",
            sources=[JobSource(source="remotive", external_id="remotive:duplicate",
                               source_url="https://example.test/duplicate", original_payload={})],
        )
        db.add_all([canonical, duplicate])
        db.flush()
        canonical_id, duplicate_id = canonical.id, duplicate.id
        duplicate_analysis = AIJobAnalysis(
            job_id=duplicate_id, request_hash="a" * 64, model="fake-model",
            prompt_version="test", classification="relevant", score=90,
            rationale="Cached duplicate result", strengths=[], gaps=[], unknowns=[],
        )
        db.add(duplicate_analysis)
        if canonical_has_analysis:
            db.add(AIJobAnalysis(
                job_id=canonical_id, request_hash="b" * 64, model="fake-model",
                prompt_version="test", classification="maybe", score=50,
                rationale="Canonical result", strengths=[], gaps=[], unknowns=[],
            ))
        db.commit()

        import_jobs(db, [NormalizedJob(
            source="remotive", external_id="remotive:duplicate",
            title="Backend Engineer", company="Example", location="São Paulo",
            source_url="https://example.test/duplicate",
        )])

        assert db.get(Job, duplicate_id) is None
        analyses = list(db.scalars(select(AIJobAnalysis)).all())
        assert len(analyses) == 1
        assert analyses[0].job_id == canonical_id
        assert analyses[0].rationale == (
            "Canonical result" if canonical_has_analysis else "Cached duplicate result"
        )
