import httpx
import pytest

from app.adapters.greenhouse import GreenhouseAdapter, GreenhouseSourceError


def test_greenhouse_adapter_normalizes_published_jobs_and_skips_prospect_posts():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.url.path.endswith("/boards/venture"):
            return httpx.Response(200, json={"name": "Venture Co"})
        if request.url.path.endswith("/boards/venture/jobs"):
            assert request.url.params["content"] == "true"
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 81,
                            "internal_job_id": 901,
                            "title": "Backend Engineer",
                            "location": {"name": "São Paulo, SP"},
                            "absolute_url": "https://boards.greenhouse.io/venture/jobs/81",
                            "first_published": "2026-09-15T10:00:00Z",
                            "content": "&amp;lt;div&amp;gt;&amp;lt;h2&amp;gt;Role&amp;lt;/h2&amp;gt;"
                            "&amp;lt;p&amp;gt;Build APIs &amp;amp; services.&amp;lt;/p&amp;gt;"
                            "&amp;lt;script&amp;gt;ignore me&amp;lt;/script&amp;gt;&amp;lt;/div&amp;gt;",
                        },
                        {
                            "id": 82,
                            "internal_job_id": None,
                            "title": "General interest",
                            "absolute_url": "https://boards.greenhouse.io/venture/jobs/82",
                        },
                    ]
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    jobs = GreenhouseAdapter("venture", client=client).fetch_jobs()
    client.close()

    assert len(requests) == 2
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "greenhouse"
    assert job.external_id == "venture:81"
    assert job.title == "Backend Engineer"
    assert job.company == "Venture Co"
    assert job.location == "São Paulo, SP"
    assert job.description == "Role\nBuild APIs & services."
    assert job.published_at.isoformat() == "2026-09-15T10:00:00+00:00"
    assert job.salary_min is None
    assert job.workplace_type is None
    assert str(job.source_url) == "https://boards.greenhouse.io/venture/jobs/81"


def test_greenhouse_adapter_reports_http_errors_without_response_body():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(404, json={"secret": "not exposed"}))
    )
    adapter = GreenhouseAdapter("missing", client=client)

    with pytest.raises(GreenhouseSourceError, match="HTTP 404") as raised:
        adapter.fetch_jobs()

    client.close()
    assert "not exposed" not in str(raised.value)


def test_greenhouse_adapter_rejects_invalid_board_tokens():
    with pytest.raises(GreenhouseSourceError, match="caracteres inválidos"):
        GreenhouseAdapter("https://boards.greenhouse.io/company")
