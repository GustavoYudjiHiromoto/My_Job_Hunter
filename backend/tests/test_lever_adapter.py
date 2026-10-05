from datetime import UTC, datetime

import httpx
import pytest

from app.adapters.lever import LeverAdapter, LeverSourceError


def test_lever_adapter_normalizes_published_postings_and_paginates():
    requests = []
    epoch_ms = 1760000000000
    postings = [
        {
            "id": "posting-1",
            "text": "Backend Engineer",
            "categories": {
                "location": "São Paulo, SP",
                "commitment": "Regular Full Time",
                "allLocations": ["São Paulo, SP"],
            },
            "descriptionPlain": "Build backend services.",
            "additionalPlain": "Benefits are listed here.",
            "lists": [{"text": "Requirements", "content": "<ul><li>Python &amp; SQL</li></ul>"}],
            "workplaceType": "remote",
            "createdAt": epoch_ms,
            "hostedUrl": "https://jobs.lever.co/acme/posting-1",
            "salaryRange": {"min": 100000, "max": 140000, "currency": "USD", "interval": "per-year"},
        },
        {
            "id": "posting-2",
            "text": "Support Engineer",
            "categories": {},
            "workplaceType": "unspecified",
        },
        {
            "id": "posting-3",
            "text": "Data Engineer",
            "categories": {"location": "Remote - Brazil"},
            "hostedUrl": "https://jobs.lever.co/acme/posting-3",
        },
    ]

    def handler(request: httpx.Request):
        requests.append(request)
        skip = int(request.url.params["skip"])
        assert request.url.params["mode"] == "json"
        assert request.headers["accept"] == "application/json"
        return httpx.Response(200, json=postings[skip : skip + 2])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    jobs = LeverAdapter("acme", client=client, page_size=2).fetch_jobs()
    client.close()

    assert [request.url.params["skip"] for request in requests] == ["0", "2"]
    assert len(jobs) == 3
    first = jobs[0]
    assert first.source == "lever"
    assert first.external_id == "acme:posting-1"
    assert first.company == "Acme"
    assert first.location == "São Paulo, SP"
    assert first.workplace_type == "Remoto"
    assert first.employment_type == "Regular Full Time"
    assert (
        first.description
        == "Build backend services.\n\nBenefits are listed here.\n\nRequirements\n\nPython & SQL"
    )
    assert first.published_at == datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)
    assert first.salary_min is None
    assert str(first.source_url) == "https://jobs.lever.co/acme/posting-1"
    assert jobs[1].location is None
    assert jobs[1].workplace_type is None
    assert jobs[1].published_at is None
    assert str(jobs[1].source_url) == "https://jobs.lever.co/acme/posting-2"


def test_lever_adapter_uses_eu_region_and_reports_http_errors_safely():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(403, json={"secret": "not exposed"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = LeverAdapter("missing-site", region="eu", client=client)

    with pytest.raises(LeverSourceError, match="HTTP 403") as raised:
        adapter.fetch_jobs()

    client.close()
    assert requests[0].url.host == "api.eu.lever.co"
    assert "not exposed" not in str(raised.value)


def test_lever_adapter_rejects_invalid_site_and_region():
    with pytest.raises(LeverSourceError, match="caracteres inválidos"):
        LeverAdapter("https://jobs.lever.co/company")
    with pytest.raises(LeverSourceError, match="global ou eu"):
        LeverAdapter("company", region="apac")


def test_lever_adapter_rejects_invalid_payload_and_repeated_pages():
    malformed = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": []})))
    with pytest.raises(LeverSourceError, match="lista de postings inválida"):
        LeverAdapter("company", client=malformed).fetch_jobs()
    malformed.close()

    repeated = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[{"id": "same", "text": "Backend"}]))
    )
    with pytest.raises(LeverSourceError, match="Paginação repetida"):
        LeverAdapter("company", client=repeated, page_size=1).fetch_jobs()
    repeated.close()
