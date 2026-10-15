import httpx
import pytest

from app.adapters.discovery import JOBICY_ROOT, DiscoveryProviderError, JobicyDiscoveryAdapter


def _record():
    return {
        "id": "job-123",
        "jobTitle": "Backend Developer",
        "companyName": "Example Remote",
        "jobGeo": "Brazil",
        "jobLevel": "Entry-level",
        "jobType": "Full-time",
        "jobDescription": "<p>Build APIs with Python.</p>",
        "url": "https://jobicy.com/jobs/123-backend-developer",
        "pubDate": "2026-10-10T10:00:00Z",
        "salaryMin": 3000,
        "salaryMax": 5000,
        "salaryCurrency": "BRL",
    }


def test_jobicy_adapter_uses_public_api_once_without_auth_and_normalizes_job():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"jobs": [_record()]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = JobicyDiscoveryAdapter(client).search("Backend Developer Python", geo="brazil", limit=200)

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url).startswith(JOBICY_ROOT)
    assert dict(request.url.params) == {"tag": "Backend Developer Python", "geo": "brazil", "count": "200"}
    assert "authorization" not in request.headers
    job = jobs[0]
    assert job.source == "jobicy"
    assert job.external_id == "job-123"
    assert job.description == "Build APIs with Python."
    assert job.location == "Brazil"
    assert job.workplace_type == "Remoto"
    assert job.seniority == "Entry-level"
    assert job.employment_type == "Full-time"
    assert job.salary_min == 3000 and job.salary_max == 5000
    assert job.salary_currency == "BRL"
    assert str(job.source_url) == "https://jobicy.com/jobs/123-backend-developer"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"jobs": "invalid"}),
        httpx.Response(200, json={"jobs": [{}]}),
    ],
)
def test_jobicy_adapter_reports_http_and_invalid_payloads(response):
    with httpx.Client(transport=httpx.MockTransport(lambda _request: response)) as client:
        with pytest.raises(DiscoveryProviderError):
            JobicyDiscoveryAdapter(client).search("Backend Developer")
