import json

import httpx
import pytest

from app.providers.ai.openrouter import AIProviderError
from app.providers.ai.openrouter_resume import OpenRouterResumeParser
from app.schemas.resume_import import ResumeEducationDraft, ResumeExperienceDraft, ResumeImportDraft
from app.services.resume_import import ResumeImportError, extract_resume_text


def test_extract_resume_text_rejects_invalid_pdf_without_exposing_payload():
    secret = b"not a pdf with personal information"
    try:
        extract_resume_text(secret)
    except ResumeImportError as error:
        assert error.code == "invalid_pdf"
        assert "personal information" not in str(error)
    else:
        raise AssertionError("Expected invalid PDF error")


def test_openrouter_resume_parser_uses_structured_output_and_safe_errors(monkeypatch):
    client_class = httpx.Client
    output = {
        "professional_summary": "Backend developer",
        "skills": "Python",
        "languages": "Português",
        "experiences": [],
        "education": [],
    }
    request_data = {}

    def handler(request):
        request_data["authorization"] = request.headers["authorization"]
        request_data["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(output)}}]},
        )

    monkeypatch.setattr(
        "app.providers.ai.openrouter_resume.httpx.Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = OpenRouterResumeParser("secret-key", "test/model").parse("private resume text")
    assert result.professional_summary == "Backend developer"
    assert request_data["authorization"] == "Bearer secret-key"
    assert request_data["payload"]["messages"][1]["content"] == "private resume text"
    assert request_data["payload"]["response_format"]["json_schema"]["strict"] is True
    assert "email" not in result.model_dump()

    def invalid_handler(_request):
        return httpx.Response(200, json={"choices": []})

    monkeypatch.setattr(
        "app.providers.ai.openrouter_resume.httpx.Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(invalid_handler), **kwargs),
    )
    with pytest.raises(AIProviderError) as error:
        OpenRouterResumeParser("secret-key", "test/model").parse("private resume text")
    assert str(error.value) == "resume_import_unavailable"
    assert "private resume text" not in str(error.value)
    assert "secret-key" not in str(error.value)


def test_preview_requires_consent_before_calling_openrouter(client, monkeypatch):
    import app.api.routes.profile as profile_route

    monkeypatch.setattr(profile_route, "extract_resume_text", lambda _data: "CV local")
    monkeypatch.setattr(
        profile_route,
        "OpenRouterResumeParser",
        lambda *_args: (_ for _ in ()).throw(AssertionError("provider should not be called")),
    )
    response = client.post(
        "/api/profile/resume-import/preview",
        files={"file": ("cv.pdf", b"%PDF-test", "application/pdf")},
        data={"consent_to_openrouter": "false"},
    )
    assert response.status_code == 400
    assert "autorizar" in response.json()["detail"]


def test_preview_without_api_key_never_calls_provider(client, monkeypatch):
    import app.api.routes.profile as profile_route

    monkeypatch.setattr(profile_route, "extract_resume_text", lambda _data: "Texto local")
    monkeypatch.setattr(profile_route, "get_ai_api_key", lambda: "")
    monkeypatch.setattr(
        profile_route,
        "OpenRouterResumeParser",
        lambda *_args: (_ for _ in ()).throw(AssertionError("provider should not be called")),
    )
    response = client.post(
        "/api/profile/resume-import/preview",
        files={"file": ("cv.pdf", b"%PDF-test", "application/pdf")},
        data={"consent_to_openrouter": "true"},
    )
    assert response.status_code == 503
    assert "OPENROUTER_API_KEY" in response.json()["detail"]


def test_preview_is_temporary_and_returns_editable_draft_without_identity_fields(client, monkeypatch):
    import app.api.routes.profile as profile_route

    monkeypatch.setattr(profile_route, "get_ai_api_key", lambda: "test-key")
    monkeypatch.setattr(profile_route, "extract_resume_text", lambda _data: "Texto de currículo")

    class FakeParser:
        def __init__(self, *_args):
            pass

        def parse(self, text):
            assert text == "Texto de currículo"
            return ResumeImportDraft(
                professional_summary="Backend developer",
                skills="Python, FastAPI",
                languages="Português",
                experiences=[ResumeExperienceDraft(company="Acme", role="Dev")],
                education=[ResumeEducationDraft(institution="USP", degree="Computação")],
            )

    monkeypatch.setattr(profile_route, "OpenRouterResumeParser", FakeParser)
    response = client.post(
        "/api/profile/resume-import/preview",
        files={"file": ("cv.pdf", b"%PDF-test", "application/pdf")},
        data={"consent_to_openrouter": "true"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["resume_text"] == "Texto de currículo"
    assert result["experiences"][0]["company"] == "Acme"
    assert "full_name" not in result and "email" not in result


def test_preview_maps_provider_failure_to_safe_message(client, monkeypatch):
    import app.api.routes.profile as profile_route

    monkeypatch.setattr(profile_route, "get_ai_api_key", lambda: "test-key")
    monkeypatch.setattr(profile_route, "extract_resume_text", lambda _data: "private resume")

    class FailingParser:
        def __init__(self, *_args):
            pass

        def parse(self, _text):
            raise AIProviderError("secret provider body")

    monkeypatch.setattr(profile_route, "OpenRouterResumeParser", FailingParser)
    response = client.post(
        "/api/profile/resume-import/preview",
        files={"file": ("cv.pdf", b"%PDF-test", "application/pdf")},
        data={"consent_to_openrouter": "true"},
    )
    assert response.status_code == 502
    assert "secret" not in response.text and "private resume" not in response.text


def test_apply_saves_selected_data_and_merges_records_idempotently(client):
    existing = client.put("/api/profile", json={"full_name": "Ana", "email": "ana@example.com"}).json()
    draft = {
        "professional_summary": "Resumo atualizado",
        "skills": "Python",
        "languages": "Português",
        "resume_text": "CV editado",
        "experiences": [{
            "company": "Acme", "role": "Engenheira", "location": "São Paulo", "description": "APIs",
            "start_date": "2021-01-01", "end_date": None, "is_current": True,
        }],
        "education": [{
            "institution": "USP", "degree": "Bacharelado", "field_of_study": "Computação",
            "start_year": 2018, "end_year": 2022,
        }],
    }
    payload = {
        "sections": ["professional_summary", "skills", "resume_text", "experiences", "education"],
        "draft": draft,
    }
    first = client.put("/api/profile/resume-import/apply", json=payload)
    second = client.put("/api/profile/resume-import/apply", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["experiences_added"] == 1 and first.json()["education_added"] == 1
    assert second.json()["experiences_added"] == 0 and second.json()["education_added"] == 0
    profile = client.get("/api/profile").json()
    assert profile["full_name"] == existing["full_name"] == "Ana"
    assert profile["email"] == "ana@example.com"
    assert profile["professional_summary"] == "Resumo atualizado"
    assert profile["languages"] == ""
    assert profile["resume_text"] == "CV editado"
    assert len(profile["experiences"]) == 1 and len(profile["education"]) == 1


def test_apply_rejects_invalid_date_ranges_without_partial_write(client):
    client.put("/api/profile", json={"professional_summary": "Antes"})
    response = client.put("/api/profile/resume-import/apply", json={
        "sections": ["professional_summary", "experiences"],
        "draft": {
            "professional_summary": "Depois", "skills": "", "languages": "", "resume_text": "",
            "experiences": [{
                "company": "Acme", "role": "Dev", "start_date": "2024-01-01", "end_date": "2020-01-01",
            }],
            "education": [],
        },
    })
    assert response.status_code == 422
    assert client.get("/api/profile").json()["professional_summary"] == "Antes"
