import httpx
import pytest

from app.adapters.discovery import DiscoveryProviderError, JSearchDiscoveryAdapter


def _job_record():
    return {
        "job_id": "encoded-provider-id",
        "job_title": "Backend Developer",
        "employer_name": "Example Co",
        "job_apply_link": "https://example.com/jobs/123",
        "job_description": "<p>Build services with Java and Python.</p>",
        "job_city": "São Paulo",
        "job_state": "SP",
        "job_country": "Brazil",
        "job_is_remote": True,
        "work_arrangement": "hybrid",
        "seniority_level": "junior",
        "job_employment_type": "Internship",
        "job_min_salary": 3000,
        "job_max_salary": 5000,
        "job_salary_currency": "BRL",
        "job_posted_at_datetime_utc": "2026-10-10T10:00:00Z",
        "job_publisher": "Example Board",
        "apply_options": [{"apply_link": "https://example.com/jobs/123"}],
    }


def test_jsearch_adapter_sends_key_in_header_and_normalizes_response(monkeypatch):
    api_key = "test-api-key"
    monkeypatch.setenv("JSEARCH_API_KEY", api_key)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": {"jobs": [_job_record()]}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = JSearchDiscoveryAdapter(client).search(
            "backend java São Paulo", work_from_home=False
        )

    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/jsearch/search-v2"
    assert request.headers["x-api-key"] == api_key
    assert api_key not in str(request.url)
    assert request.url.params["query"] == "backend java São Paulo"
    assert request.url.params["country"] == "br"
    assert request.url.params["language"] == "pt"
    assert request.url.params["work_from_home"] == "false"

    job = jobs[0]
    assert job.source == "jsearch"
    assert job.external_id == "encoded-provider-id"
    assert job.title == "Backend Developer"
    assert job.company == "Example Co"
    assert job.description == "Build services with Java and Python."
    assert job.location == "São Paulo, SP, Brazil"
    assert job.workplace_type == "hybrid"
    assert job.seniority == "junior"
    assert job.employment_type == "Internship"
    assert job.salary_min == 3000
    assert job.salary_max == 5000
    assert job.salary_currency == "BRL"
    assert str(job.source_url) == "https://example.com/jobs/123"
    assert job.original_payload["job_publisher"] == "Example Board"


def test_jsearch_adapter_accepts_documented_response_envelope(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-api-key")
    payload = {
        "status": "OK",
        "request_id": "request-id",
        "data": {"jobs": [_job_record()], "cursor": "next-page"},
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    ) as client:
        jobs = JSearchDiscoveryAdapter(client).search("backend São Paulo")

    assert len(jobs) == 1
    assert jobs[0].source == "jsearch"
    assert jobs[0].external_id == "encoded-provider-id"
    assert jobs[0].title == "Backend Developer"
    assert jobs[0].company == "Example Co"
    assert str(jobs[0].source_url) == "https://example.com/jobs/123"


def test_jsearch_adapter_accepts_empty_jobs_list_as_valid_response(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-api-key")
    payload = {"status": "OK", "request_id": "request-id", "data": {"jobs": [], "cursor": None}}
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    ) as client:
        jobs = JSearchDiscoveryAdapter(client).search("backend São Paulo")

    assert jobs == []


@pytest.mark.parametrize(
    "external_id",
    ["provider-id", "x" * 200],
)
def test_jsearch_keeps_valid_external_ids_unchanged(external_id, monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-api-key")
    record = {**_job_record(), "job_id": external_id}
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"data": {"jobs": [record]}})
        )
    ) as client:
        jobs = JSearchDiscoveryAdapter(client).search("backend")

    assert jobs[0].external_id == external_id
    assert jobs[0].original_payload["job_id"] == external_id


def test_jsearch_long_external_id_uses_deterministic_bounded_identity(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-api-key")
    long_id = "synthetic-provider-id-" + "x" * 240
    distinct_long_id = "synthetic-provider-id-" + "y" * 240

    def normalize_id(provider_id):
        record = {**_job_record(), "job_id": provider_id}
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"data": {"jobs": [record]}})
            )
        ) as client:
            return JSearchDiscoveryAdapter(client).search("backend")[0]

    first = normalize_id(long_id)
    repeated = normalize_id(long_id)
    different = normalize_id(distinct_long_id)

    assert first.external_id.startswith("jsearch-sha256:")
    assert len(first.external_id) <= 200
    assert first.external_id == repeated.external_id
    assert first.external_id != different.external_id
    assert first.original_payload["job_id"] == long_id
    assert first.title == "Backend Developer"
    assert first.company == "Example Co"
    assert first.description == "Build services with Java and Python."
    assert first.location == "São Paulo, SP, Brazil"
    assert str(first.source_url) == "https://example.com/jobs/123"


def test_jsearch_realistic_synthetic_response_with_long_id_normalizes(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-api-key")
    synthetic_long_id = "synthetic-long-job-id-" + "z" * 220
    response_payload = {
        "status": "OK",
        "request_id": "synthetic-request-id",
        "data": {
            "jobs": [{**_job_record(), "job_id": synthetic_long_id}],
            "cursor": None,
        },
    }
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=response_payload)
        )
    ) as client:
        jobs = JSearchDiscoveryAdapter(client).search("backend São Paulo")

    assert len(jobs) == 1
    assert jobs[0].external_id.startswith("jsearch-sha256:")
    assert len(jobs[0].external_id) <= 200
    assert jobs[0].original_payload["job_id"] == synthetic_long_id
    assert jobs[0].title == "Backend Developer"
    assert jobs[0].company == "Example Co"
    assert str(jobs[0].source_url) == "https://example.com/jobs/123"


def test_jsearch_validation_diagnostic_contains_only_field_path_and_error_type(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-api-key")
    sensitive_marker = "DO_NOT_EXPOSE_" + "x" * 200
    record = {**_job_record(), "job_title": sensitive_marker}
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"data": {"jobs": [record]}})
        )
    ) as client:
        with pytest.raises(DiscoveryProviderError) as error:
            JSearchDiscoveryAdapter(client).search("backend")

    diagnostic = error.value.diagnostic
    assert diagnostic is not None
    assert diagnostic.stage == "normalize_record"
    assert diagnostic.exception_type == "ValidationError"
    assert [(issue.loc, issue.error_type) for issue in diagnostic.issues] == [
        (("title",), "string_too_long")
    ]
    assert diagnostic.record_index == 0
    assert sensitive_marker not in str(error.value)
    assert sensitive_marker not in repr(diagnostic)
    assert error.value.__cause__ is None


def test_jsearch_manual_required_field_diagnostic_uses_adapter_defined_names(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-api-key")
    record = {**_job_record(), "job_title": "   "}
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"data": {"jobs": [record]}})
        )
    ) as client:
        with pytest.raises(DiscoveryProviderError) as error:
            JSearchDiscoveryAdapter(client).search("backend")

    diagnostic = error.value.diagnostic
    assert diagnostic is not None
    assert diagnostic.stage == "normalize_record"
    assert diagnostic.exception_type == "_JSearchNormalizationError"
    assert diagnostic.code == "required_fields_missing"
    assert diagnostic.fields == ("job_title",)
    assert "   " not in str(error.value)


def test_jsearch_non_object_job_is_wrapped_as_safe_normalization_error(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-api-key")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"data": {"jobs": ["sensitive record"]}})
        )
    ) as client:
        with pytest.raises(DiscoveryProviderError) as error:
            JSearchDiscoveryAdapter(client).search("backend")

    diagnostic = error.value.diagnostic
    assert diagnostic is not None
    assert diagnostic.stage == "normalize_record"
    assert diagnostic.exception_type == "TypeError"
    assert diagnostic.code == "record_not_object"
    assert diagnostic.fields == ("data.jobs",)
    assert diagnostic.record_index == 0
    assert "sensitive record" not in str(error.value)
    assert error.value.__cause__ is None


def test_jsearch_adapter_uses_first_apply_option_when_primary_link_missing(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-api-key")
    record = _job_record()
    record.pop("job_apply_link")
    record["apply_options"] = [
        {"publisher": "Board", "apply_link": "https://board.example/jobs/123"}
    ]
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"data": {"jobs": [record]}}))
    ) as client:
        jobs = JSearchDiscoveryAdapter(client).search("backend remote", work_from_home=True)
    assert str(jobs[0].source_url) == "https://board.example/jobs/123"


def test_jsearch_adapter_truncates_results_to_requested_limit(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-api-key")
    records = [{**_job_record(), "job_id": f"job-{index}"} for index in range(30)]
    requests = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                requests.append(request)
                or httpx.Response(200, json={"data": {"jobs": records}})
            )
        )
    ) as client:
        jobs = JSearchDiscoveryAdapter(client).search("backend", limit=25)
    assert len(requests) == 1
    assert len(jobs) == 25


def test_jsearch_missing_key_fails_without_making_request(monkeypatch):
    monkeypatch.delenv("JSEARCH_API_KEY", raising=False)
    requests = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
        with pytest.raises(DiscoveryProviderError, match="JSEARCH_API_KEY"):
            JSearchDiscoveryAdapter(client).search("backend developer")
    assert requests == []


def test_jsearch_http_error_does_not_expose_api_key(monkeypatch):
    api_key = "secret-test-api-key"
    monkeypatch.setenv("JSEARCH_API_KEY", api_key)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(429, json={"error": "limit"}))
    ) as client:
        with pytest.raises(DiscoveryProviderError) as error:
            JSearchDiscoveryAdapter(client).search("backend developer")
    assert "HTTP 429" in str(error.value)
    assert api_key not in str(error.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"data": {"jobs": "invalid"}}),
        httpx.Response(200, json={"data": {"jobs": [{}]}}),
    ],
)
def test_jsearch_invalid_response_is_reported(response, monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-api-key")
    with httpx.Client(transport=httpx.MockTransport(lambda _request: response)) as client:
        with pytest.raises(DiscoveryProviderError):
            JSearchDiscoveryAdapter(client).search("backend developer")
