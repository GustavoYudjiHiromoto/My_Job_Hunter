from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import main
from app.adapters.discovery import JobicyDiscoveryAdapter, JSearchDiscoveryAdapter, RemotiveDiscoveryAdapter
from app.models import (
    DiscoveryQuery,
    ImportRun,
    ImportRunSource,
    JobDiscovery,
    JobEligibility,
    JobSource,
)
from app.models.profile import Preference, ProfessionalProfile
from app.services import discovery as discovery_service
from app.services.discovery import build_jobicy_search_plans, build_jsearch_search_plans, build_search_plans


def _remotive_job():
    return {
        "id": 9876,
        "title": "Backend Developer",
        "company_name": "Example Remote",
        "description": "<p>Build APIs with Python.</p>",
        "url": "https://remotive.com/remote-jobs/software-dev/backend-developer-9876",
        "publication_date": "2026-10-10T10:00:00Z",
        "candidate_required_location": "São Paulo, SP",
        "job_type": "full_time",
    }


def _jsearch_job():
    return {
        "job_id": "js-9876",
        "job_title": "Backend Developer",
        "employer_name": "Example Remote",
        "job_apply_link": "https://remotive.com/remote-jobs/software-dev/backend-developer-9876",
        "job_description": "Build APIs with Python.",
        "job_city": "São Paulo",
        "job_state": "SP",
        "job_country": "Brazil",
        "job_is_remote": True,
    }


def _mock_remotive(monkeypatch, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.services.discovery.RemotiveDiscoveryAdapter",
        lambda: RemotiveDiscoveryAdapter(client=client),
    )
    return client


def _mock_jsearch(monkeypatch, handler):
    monkeypatch.setenv("JSEARCH_API_KEY", "test-jsearch-key")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.services.discovery.JSearchDiscoveryAdapter",
        lambda: JSearchDiscoveryAdapter(client=client),
    )
    return client


def _mock_jobicy(monkeypatch, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.services.discovery.JobicyDiscoveryAdapter",
        lambda: JobicyDiscoveryAdapter(client=client),
    )
    return client


def test_jobicy_planner_uses_profile_fields_for_one_remote_brazil_query():
    profile = ProfessionalProfile(
        professional_summary="Never search this",
        preference=Preference(
            desired_titles="Backend Developer",
            search_keywords="Python",
            search_areas="Data",
            seniority="Junior",
        ),
    )
    plans = build_jobicy_search_plans(profile)
    assert len(plans) == 1
    assert plans[0].provider == "jobicy"
    assert plans[0].strategy == "remote_brazil"
    assert plans[0].parameters == {
        "tag": "Backend Developer Python Data Junior",
        "geo": "brazil",
        "count": 25,
    }
    assert "Never search" not in plans[0].parameters["tag"]


def test_remotive_search_planner_uses_structured_fields_and_caps_queries():
    profile = ProfessionalProfile(
        professional_summary="Do not search this phrase",
        resume_text="Do not search this either",
        preference=Preference(
            desired_titles="Backend Developer\nbackend developer",
            search_keywords="Python\nSQL",
            search_areas="Software\nData\nAnalytics\nCloud\nExtra",
        ),
    )

    plans = build_search_plans(profile)

    assert len(plans) == 4
    assert all(plan.provider == "remotive" and plan.strategy == "remote" for plan in plans)
    assert all("Do not search" not in plan.parameters["search"] for plan in plans)
    assert plans[0].parameters["limit"] == 25
    assert plans[0].terms == ["Software", "Backend Developer", "Python", "SQL"]


def test_jsearch_planner_builds_distinct_local_and_remote_queries_from_preferences():
    profile = ProfessionalProfile(
        professional_summary="Never send this summary",
        resume_text="Never send résumé content",
        preference=Preference(
            desired_titles="Backend Developer",
            search_keywords="Java\nPython",
            search_areas="Software",
            desired_locations="São Paulo",
            seniority="Junior",
            employment_types="Internship",
        ),
    )

    plans = build_jsearch_search_plans(profile)

    assert [plan.strategy for plan in plans] == ["location", "remote"]
    assert "São Paulo" in plans[0].parameters["query"]
    assert plans[0].parameters["work_from_home"] is False
    assert "remote Brazil" in plans[1].parameters["query"]
    assert plans[1].parameters["work_from_home"] is True
    assert all("Junior" in plan.parameters["query"] for plan in plans)
    assert all("Internship" in plan.parameters["query"] for plan in plans)
    assert all("Never send" not in plan.parameters["query"] for plan in plans)


def test_discovery_normalizes_deduplicates_and_tracks_jsearch_queries(client, monkeypatch):
    client.put(
        "/api/profile/preferences",
        json={
            "desired_titles": "Backend Developer",
            "search_keywords": "Python",
            "search_areas": "Software\nData",
            "desired_locations": "São Paulo",
            "seniority": "Junior",
            "employment_types": "Internship",
        },
    )
    remotive_requests = []
    jsearch_requests = []

    def remotive_handler(request):
        remotive_requests.append(request)
        return httpx.Response(200, json={"jobs": [_remotive_job()]})

    def jsearch_handler(request):
        jsearch_requests.append(request)
        return httpx.Response(200, json={"data": {"jobs": [_jsearch_job()]}})

    remotive_client = _mock_remotive(monkeypatch, remotive_handler)
    jsearch_client = _mock_jsearch(monkeypatch, jsearch_handler)
    jobicy_requests = []
    jobicy_client = _mock_jobicy(
        monkeypatch,
        lambda request: (jobicy_requests.append(request) or httpx.Response(200, json={"jobs": []})),
    )
    try:
        response = client.post("/api/jobs/discover")
    finally:
        remotive_client.close()
        jsearch_client.close()
        jobicy_client.close()

    assert response.status_code == 200
    run = response.json()
    assert run["requested_source"] == "discovery"
    assert run["status"] == "succeeded"
    assert run["created"] == 1
    assert run["updated"] == 2
    assert run["total"] == 3
    assert {(source["source"], source["scope"]) for source in run["sources"]} == {
        ("remotive", "remote"),
        ("jsearch", "br"),
        ("jobicy", "brazil"),
    }
    assert len(remotive_requests) == 1
    assert len(jsearch_requests) == 2
    assert len(jobicy_requests) == 1
    assert len(remotive_requests) + len(jsearch_requests) + len(jobicy_requests) == 4
    assert [request.url.params["work_from_home"] for request in jsearch_requests] == ["false", "true"]
    assert all(request.headers["x-api-key"] == "test-jsearch-key" for request in jsearch_requests)
    assert "test-jsearch-key" not in response.text

    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Backend Developer"
    assert jobs[0]["description"] == "Build APIs with Python."
    assert jobs[0]["workplace_type"] == "Remoto"
    assert {source["source"] for source in jobs[0]["sources"]} == {"remotive", "jsearch"}

    with Session(main.engine) as db:
        source_runs = list(
            db.scalars(select(ImportRunSource).where(ImportRunSource.import_run_id == run["id"]))
        )
        queries = list(
            db.scalars(
                select(DiscoveryQuery).where(
                    DiscoveryQuery.import_run_source_id.in_([source.id for source in source_runs])
                )
            )
        )
        discoveries = list(
            db.scalars(select(JobDiscovery).where(JobDiscovery.query_id.in_([q.id for q in queries])))
        )
        eligibility = list(db.scalars(select(JobEligibility)))
        job_sources = list(
            db.scalars(select(JobSource).where(JobSource.source.in_(("remotive", "jsearch"))))
        )

    assert len(source_runs) == 3
    assert len(queries) == 4
    assert {query.provider for query in queries} == {"remotive", "jsearch", "jobicy"}
    assert len(discoveries) == 3
    assert len(eligibility) == 1
    assert eligibility[0].status == "eligible"
    assert eligibility[0].policy_version == "unconfigured"
    assert len(job_sources) == 2
    assert {source.source for source in job_sources} == {"remotive", "jsearch"}
    assert all("test-jsearch-key" not in str(query.parameters) for query in queries)


def test_discovery_failure_is_partial_and_isolated_from_m7_and_m8(client, monkeypatch):
    with Session(main.engine) as db:
        m7_run = ImportRun(requested_source="all", status="succeeded")
        db.add(m7_run)
        db.commit()
        m7_run_id = m7_run.id

    client.put(
        "/api/profile/preferences",
        json={"desired_titles": "Backend Developer", "search_areas": "Software"},
    )
    client.put(
        "/api/notifications/settings",
        json={"enabled": True, "recipient_email": "person@example.com", "minimum_score": 0},
    )
    remotive_client = _mock_remotive(
        monkeypatch, lambda _request: httpx.Response(200, json={"jobs": [_remotive_job()]})
    )
    jsearch_client = _mock_jsearch(
        monkeypatch, lambda _request: httpx.Response(503, json={"error": "unavailable"})
    )
    jobicy_client = _mock_jobicy(monkeypatch, lambda _request: httpx.Response(200, json={"jobs": []}))
    try:
        response = client.post("/api/jobs/discover")
    finally:
        remotive_client.close()
        jsearch_client.close()
        jobicy_client.close()

    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert client.get("/api/jobs/import-runs/latest").json()["id"] == m7_run_id
    assert client.get("/api/jobs/discovery-runs/latest").json()["id"] == response.json()["id"]
    assert client.get("/api/notifications").json() == []
    with Session(main.engine) as db:
        statuses = list(db.scalars(select(DiscoveryQuery.status).order_by(DiscoveryQuery.id)))
    assert statuses == ["succeeded", "failed", "failed", "succeeded"]


def test_discovery_requires_structured_search_terms(client):
    response = client.post("/api/jobs/discover")

    assert response.status_code == 422
    assert "Cadastre ao menos" in response.json()["detail"]
    assert client.get("/api/jobs").json() == []


def test_missing_jsearch_key_skips_optional_provider_and_keeps_remotive_results(client, monkeypatch):
    monkeypatch.delenv("JSEARCH_API_KEY", raising=False)
    client.put(
        "/api/profile/preferences",
        json={"desired_titles": "Backend Developer", "search_areas": "Software"},
    )
    remotive_client = _mock_remotive(
        monkeypatch, lambda _request: httpx.Response(200, json={"jobs": [_remotive_job()]})
    )
    jobicy_client = _mock_jobicy(monkeypatch, lambda _request: httpx.Response(200, json={"jobs": []}))
    monkeypatch.delenv("JSEARCH_API_KEY", raising=False)
    try:
        response = client.post("/api/jobs/discover")
    finally:
        remotive_client.close()
        jobicy_client.close()

    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "succeeded"
    assert {source["source"]: source["status"] for source in run["sources"]} == {
        "remotive": "succeeded",
        "jsearch": "skipped",
        "jobicy": "succeeded",
    }
    jsearch_source = next(source for source in run["sources"] if source["source"] == "jsearch")
    assert "JSEARCH_API_KEY" in jsearch_source["error"]
    assert len(client.get("/api/jobs").json()) == 1


def test_jsearch_429_skips_remaining_query_and_preserves_remotive(client, monkeypatch):
    client.put(
        "/api/profile/preferences",
        json={"desired_titles": "Backend Developer", "search_areas": "Software"},
    )
    requests = []
    remotive_client = _mock_remotive(
        monkeypatch, lambda _request: httpx.Response(200, json={"jobs": [_remotive_job()]})
    )

    def jsearch_handler(request):
        requests.append(request)
        return httpx.Response(429, json={"error": "quota"})

    jsearch_client = _mock_jsearch(monkeypatch, jsearch_handler)
    jobicy_client = _mock_jobicy(monkeypatch, lambda _request: httpx.Response(200, json={"jobs": []}))
    try:
        response = client.post("/api/jobs/discover")
    finally:
        remotive_client.close()
        jsearch_client.close()
        jobicy_client.close()

    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert len(requests) == 1
    assert len(client.get("/api/jobs").json()) == 1
    with Session(main.engine) as db:
        jsearch_queries = list(
            db.scalars(
                select(DiscoveryQuery)
                .where(DiscoveryQuery.provider == "jsearch")
                .order_by(DiscoveryQuery.id)
            )
        )
    assert [query.status for query in jsearch_queries] == ["failed", "skipped"]
    assert "HTTP 429" in jsearch_queries[0].error
    assert "interrompido" in jsearch_queries[1].error


def test_jobicy_failure_keeps_results_from_other_discovery_providers(client, monkeypatch):
    client.put(
        "/api/profile/preferences",
        json={"desired_titles": "Backend Developer", "search_areas": "Software"},
    )
    remotive_client = _mock_remotive(
        monkeypatch, lambda _request: httpx.Response(200, json={"jobs": [_remotive_job()]})
    )
    jsearch_client = _mock_jsearch(
        monkeypatch, lambda _request: httpx.Response(200, json={"data": {"jobs": []}})
    )
    jobicy_client = _mock_jobicy(monkeypatch, lambda _request: httpx.Response(503, json={"error": "offline"}))
    try:
        response = client.post("/api/jobs/discover")
    finally:
        remotive_client.close()
        jsearch_client.close()
        jobicy_client.close()

    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert len(client.get("/api/jobs").json()) == 1
    sources = {source["source"]: source["status"] for source in response.json()["sources"]}
    assert sources == {"remotive": "succeeded", "jsearch": "succeeded", "jobicy": "failed"}


def test_discovery_keeps_four_request_ceiling_across_all_providers(client, monkeypatch):
    client.put(
        "/api/profile/preferences",
        json={
            "desired_titles": "Backend Developer",
            "search_areas": "Software\nData\nCloud\nAnalytics\nSecurity",
        },
    )
    remotive_requests = []
    jsearch_requests = []
    remotive_client = _mock_remotive(
        monkeypatch,
        lambda request: (remotive_requests.append(request) or httpx.Response(200, json={"jobs": []})),
    )
    jsearch_client = _mock_jsearch(
        monkeypatch,
        lambda request: (
            jsearch_requests.append(request)
            or httpx.Response(200, json={"data": {"jobs": []}})
        ),
    )
    jobicy_requests = []
    jobicy_client = _mock_jobicy(
        monkeypatch,
        lambda request: (jobicy_requests.append(request) or httpx.Response(200, json={"jobs": []})),
    )
    try:
        response = client.post("/api/jobs/discover")
    finally:
        remotive_client.close()
        jsearch_client.close()
        jobicy_client.close()

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert len(remotive_requests) == 1
    assert len(jsearch_requests) == 2
    assert len(jobicy_requests) == 1
    assert len(remotive_requests) + len(jsearch_requests) + len(jobicy_requests) == 4


def test_jsearch_monthly_local_cap_skips_requests_after_200(client, monkeypatch):
    with Session(main.engine) as db:
        run = ImportRun(requested_source="discovery", status="succeeded", started_at=datetime.now(UTC))
        source = ImportRunSource(source="jsearch", scope="br", status="succeeded")
        run.sources.append(source)
        db.add(run)
        db.flush()
        for index in range(199):
            db.add(
                DiscoveryQuery(
                    import_run_source_id=source.id,
                    provider="jsearch",
                    strategy="seed",
                    query_hash=f"seed-{index}",
                    search_terms="seed",
                    parameters={},
                    status="succeeded",
                )
            )
        db.commit()

    client.put(
        "/api/profile/preferences",
        json={"desired_titles": "Backend Developer", "search_areas": "Software"},
    )
    jsearch_requests = []
    remotive_client = _mock_remotive(
        monkeypatch, lambda _request: httpx.Response(200, json={"jobs": []})
    )
    jsearch_client = _mock_jsearch(
        monkeypatch,
        lambda request: (
            jsearch_requests.append(request)
            or httpx.Response(200, json={"data": {"jobs": []}})
        ),
    )
    jobicy_client = _mock_jobicy(monkeypatch, lambda _request: httpx.Response(200, json={"jobs": []}))
    try:
        response = client.post("/api/jobs/discover")
    finally:
        remotive_client.close()
        jsearch_client.close()
        jobicy_client.close()

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert len(jsearch_requests) == 1
    jsearch_run = next(source for source in response.json()["sources"] if source["source"] == "jsearch")
    assert jsearch_run["status"] == "succeeded"
    with Session(main.engine) as db:
        latest_queries = list(
            db.scalars(
                select(DiscoveryQuery)
                .join(ImportRunSource)
                .where(ImportRunSource.import_run_id == response.json()["id"])
                .where(DiscoveryQuery.provider == "jsearch")
                .order_by(DiscoveryQuery.id)
            )
        )
    assert [query.status for query in latest_queries] == ["succeeded", "skipped"]
    assert "Limite local mensal" in latest_queries[1].error


def test_jobicy_cooldown_skips_second_run_using_discovery_history(client, monkeypatch):
    client.put(
        "/api/profile/preferences",
        json={"desired_titles": "Backend Developer", "search_keywords": "Python"},
    )
    jobicy_requests = []
    remotive_client = _mock_remotive(monkeypatch, lambda _request: httpx.Response(200, json={"jobs": []}))
    jsearch_client = _mock_jsearch(
        monkeypatch, lambda _request: httpx.Response(200, json={"data": {"jobs": []}})
    )
    jobicy_client = _mock_jobicy(
        monkeypatch,
        lambda request: (jobicy_requests.append(request) or httpx.Response(200, json={"jobs": []})),
    )
    try:
        first = client.post("/api/jobs/discover")
        second = client.post("/api/jobs/discover")
    finally:
        remotive_client.close()
        jsearch_client.close()
        jobicy_client.close()

    assert first.status_code == second.status_code == 200
    assert len(jobicy_requests) == 1
    second_jobicy = next(source for source in second.json()["sources"] if source["source"] == "jobicy")
    assert second_jobicy["status"] == "skipped"
    assert "uma hora" in second_jobicy["error"]
    with Session(main.engine) as db:
        second_query = db.scalar(
            select(DiscoveryQuery)
            .join(ImportRunSource)
            .where(ImportRunSource.import_run_id == second.json()["id"])
            .where(DiscoveryQuery.provider == "jobicy")
        )
    assert second_query.status == "skipped"


def test_jsearch_monthly_limit_uses_reservation_month_and_reserves_before_http(client, monkeypatch):
    current = {"value": datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)}
    monkeypatch.setattr(discovery_service, "_utc_now", lambda: current["value"])
    september_attempt = current["value"]

    with Session(main.engine) as db:
        run = ImportRun(
            requested_source="discovery", status="succeeded", started_at=september_attempt
        )
        source = ImportRunSource(source="jsearch", scope="br", status="succeeded")
        run.sources.append(source)
        db.add(run)
        db.flush()
        for index in range(199):
            db.add(
                DiscoveryQuery(
                    import_run_source_id=source.id,
                    provider="jsearch",
                    strategy="seed",
                    query_hash=f"september-seed-{index}",
                    search_terms="seed",
                    parameters={},
                    status="succeeded",
                    created_at=september_attempt,
                )
            )
        db.commit()

    client.put(
        "/api/profile/preferences",
        json={"desired_titles": "Backend Developer", "search_areas": "Software"},
    )
    jsearch_requests = []

    def jsearch_handler(request):
        jsearch_requests.append(request)
        with Session(main.engine) as db:
            reservation = db.scalar(
                select(DiscoveryQuery)
                .where(DiscoveryQuery.provider == "jsearch")
                .order_by(DiscoveryQuery.id.desc())
                .limit(1)
            )
            assert reservation.status == "pending"
            reserved_at = reservation.created_at
            if reserved_at.tzinfo is None:
                reserved_at = reserved_at.replace(tzinfo=UTC)
            assert reserved_at == current["value"]
        return httpx.Response(200, json={"data": {"jobs": []}})

    remotive_client = _mock_remotive(
        monkeypatch, lambda _request: httpx.Response(200, json={"jobs": []})
    )
    jsearch_client = _mock_jsearch(monkeypatch, jsearch_handler)
    jobicy_client = _mock_jobicy(
        monkeypatch, lambda _request: httpx.Response(200, json={"jobs": []})
    )
    try:
        september_run = client.post("/api/jobs/discover")
        assert september_run.status_code == 200
        assert len(jsearch_requests) == 1  # Atingiu 200; a segunda consulta foi ignorada.

        current["value"] = datetime(2026, 10, 1, 0, 0, 1, tzinfo=UTC)
        october_run = client.post("/api/jobs/discover")
    finally:
        remotive_client.close()
        jsearch_client.close()
        jobicy_client.close()

    assert october_run.status_code == 200
    assert len(jsearch_requests) == 3  # Duas consultas permitidas no novo mês.
    with Session(main.engine) as db:
        september_count = db.scalar(
            select(func.count(DiscoveryQuery.id)).where(
                DiscoveryQuery.provider == "jsearch",
                DiscoveryQuery.status.in_(("pending", "succeeded", "failed")),
                DiscoveryQuery.created_at >= datetime(2026, 9, 1, tzinfo=UTC),
                DiscoveryQuery.created_at < datetime(2026, 10, 1, tzinfo=UTC),
            )
        )
        october_queries = list(
            db.scalars(
                select(DiscoveryQuery)
                .where(DiscoveryQuery.provider == "jsearch")
                .where(DiscoveryQuery.created_at >= datetime(2026, 10, 1, tzinfo=UTC))
                .order_by(DiscoveryQuery.id)
            )
        )
    assert september_count == 200
    assert len(october_queries) == 2
    assert [query.status for query in october_queries] == ["succeeded", "succeeded"]


def test_jobicy_cooldown_uses_failed_attempt_time_and_ignores_skips(client, monkeypatch):
    current = {"value": datetime(2026, 10, 1, 10, 0, tzinfo=UTC)}
    monkeypatch.setattr(discovery_service, "_utc_now", lambda: current["value"])
    client.put(
        "/api/profile/preferences",
        json={"desired_titles": "Backend Developer", "search_keywords": "Python"},
    )
    jobicy_requests = []
    advance_before_jobicy = {"enabled": True}

    def remotive_handler(_request):
        if advance_before_jobicy["enabled"]:
            # A simulação representa tempo gasto em outras fontes da mesma execução.
            current["value"] = datetime(2026, 10, 1, 10, 5, tzinfo=UTC)
            advance_before_jobicy["enabled"] = False
        return httpx.Response(200, json={"jobs": []})

    def jobicy_handler(request):
        jobicy_requests.append(request)
        if len(jobicy_requests) == 1:
            return httpx.Response(503, json={"error": "temporary failure"})
        return httpx.Response(200, json={"jobs": []})

    remotive_client = _mock_remotive(monkeypatch, remotive_handler)
    jsearch_client = _mock_jsearch(
        monkeypatch, lambda _request: httpx.Response(200, json={"data": {"jobs": []}})
    )
    jobicy_client = _mock_jobicy(monkeypatch, jobicy_handler)
    try:
        failed_run = client.post("/api/jobs/discover")
        with Session(main.engine) as db:
            failed_query = db.scalar(
                select(DiscoveryQuery)
                .where(DiscoveryQuery.provider == "jobicy")
                .order_by(DiscoveryQuery.id.desc())
                .limit(1)
            )
            failed_run_row = db.get(ImportRun, failed_run.json()["id"])
            assert failed_query.status == "failed"
            assert failed_query.created_at.replace(tzinfo=UTC) == datetime(
                2026, 10, 1, 10, 5, tzinfo=UTC
            )
            assert failed_run_row.started_at.replace(tzinfo=UTC) == datetime(
                2026, 10, 1, 10, 0, tzinfo=UTC
            )

        current["value"] = datetime(2026, 10, 1, 11, 4, 59, tzinfo=UTC)
        skipped_run = client.post("/api/jobs/discover")
        current["value"] = datetime(2026, 10, 1, 11, 5, tzinfo=UTC)
        eligible_run = client.post("/api/jobs/discover")
    finally:
        remotive_client.close()
        jsearch_client.close()
        jobicy_client.close()

    assert failed_run.status_code == skipped_run.status_code == eligible_run.status_code == 200
    assert len(jobicy_requests) == 2
    with Session(main.engine) as db:
        all_jobicy_queries = list(
            db.scalars(
                select(DiscoveryQuery)
                .where(DiscoveryQuery.provider == "jobicy")
                .order_by(DiscoveryQuery.id)
            )
        )
        assert all_jobicy_queries[0].status == "failed"
        assert all_jobicy_queries[1].status == "skipped"
        assert all_jobicy_queries[2].status == "succeeded"
        assert all_jobicy_queries[0].created_at.replace(tzinfo=UTC) == datetime(
            2026, 10, 1, 10, 5, tzinfo=UTC
        )
        assert all_jobicy_queries[2].created_at.replace(tzinfo=UTC) == datetime(
            2026, 10, 1, 11, 5, tzinfo=UTC
        )
