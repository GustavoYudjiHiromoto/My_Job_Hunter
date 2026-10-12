def test_fixture_import_creates_jobs_with_origin_records(client):
    imported = client.post("/api/jobs/import-fixture")

    assert imported.status_code == 200
    assert imported.json() == {"source": "fixture", "created": 4, "updated": 0, "total": 4}

    jobs = client.get("/api/jobs")
    assert jobs.status_code == 200
    assert len(jobs.json()) == 4

    missing_data = next(job for job in jobs.json() if job["sources"][0]["external_id"] == "demo-003")
    assert missing_data["location"] is None
    assert missing_data["salary_min"] is None
    assert missing_data["sources"][0]["source"] == "fixture"
    assert missing_data["sources"][0]["external_id"] == "demo-003"
    assert missing_data["sources"][0]["source_url"] == "https://example.com/jobs/demo-003"


def test_reimport_updates_existing_jobs_without_duplicating_them(client):
    first_import = client.post("/api/jobs/import-fixture").json()
    first_ids = {job["id"] for job in client.get("/api/jobs").json()}

    second_import = client.post("/api/jobs/import-fixture")

    assert second_import.status_code == 200
    assert second_import.json() == {"source": "fixture", "created": 0, "updated": 4, "total": 4}
    assert first_import["created"] == 4
    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 4
    assert {job["id"] for job in jobs} == first_ids


def test_job_details_include_original_source_and_unknown_job_returns_404(client):
    client.post("/api/jobs/import-fixture")
    jobs = client.get("/api/jobs").json()
    job_id = jobs[0]["id"]

    detail = client.get(f"/api/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == job_id
    assert detail.json()["sources"][0]["source_url"].startswith("https://example.com/")
    assert client.get("/api/jobs/999999").status_code == 404


def test_greenhouse_import_reports_partial_board_errors(client, monkeypatch):
    from app.adapters.greenhouse import GreenhouseSourceError
    from app.schemas.jobs import NormalizedJob

    class FakeGreenhouseAdapter:
        source_name = "greenhouse"

        def __init__(self, board_token):
            self.board_token = board_token

        def fetch_jobs(self):
            if self.board_token == "unavailable":
                raise GreenhouseSourceError("HTTP 503 para board 'unavailable'.")
            return [
                NormalizedJob(
                    source="greenhouse",
                    external_id=f"{self.board_token}:101",
                    title="Platform Engineer",
                    company="Example Ltd",
                    source_url="https://boards.greenhouse.io/example/jobs/101",
                )
            ]

    monkeypatch.setattr(
        "app.api.routes.jobs.get_greenhouse_board_tokens",
        lambda: ["example", "unavailable"],
    )
    monkeypatch.setattr("app.services.jobs.GreenhouseAdapter", FakeGreenhouseAdapter)

    response = client.post("/api/jobs/import-greenhouse")

    assert response.status_code == 200
    assert response.json()["boards_configured"] == 2
    assert response.json()["boards_succeeded"] == 1
    assert response.json()["created"] == 1
    assert response.json()["errors"] == [
        {"board_token": "unavailable", "message": "HTTP 503 para board 'unavailable'."}
    ]
    stored = client.get("/api/jobs").json()
    assert len(stored) == 1
    assert stored[0]["sources"][0]["source"] == "greenhouse"


def test_greenhouse_import_requires_board_configuration(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.jobs.get_greenhouse_board_tokens", lambda: [])

    response = client.post("/api/jobs/import-greenhouse")

    assert response.status_code == 503
    assert "GREENHOUSE_BOARDS" in response.json()["detail"]


def test_lever_import_reports_partial_site_errors(client, monkeypatch):
    from app.adapters.lever import LeverSourceError
    from app.schemas.jobs import NormalizedJob

    class FakeLeverAdapter:
        def __init__(self, site, region):
            self.site = site
            self.region = region

        def fetch_jobs(self):
            if self.site == "unavailable":
                raise LeverSourceError("Lever retornou HTTP 503 para o site 'unavailable'.")
            return [
                NormalizedJob(
                    source="lever",
                    external_id=f"{self.site}:101",
                    title="Platform Engineer",
                    company="Example Ltd",
                    source_url="https://jobs.lever.co/example/101",
                )
            ]

    monkeypatch.setattr("app.api.routes.jobs.get_lever_sites", lambda: ["example", "unavailable"])
    monkeypatch.setattr("app.api.routes.jobs.get_lever_region", lambda: "eu")
    monkeypatch.setattr("app.services.jobs.LeverAdapter", FakeLeverAdapter)

    response = client.post("/api/jobs/import-lever")

    assert response.status_code == 200
    assert response.json()["sites_configured"] == 2
    assert response.json()["sites_succeeded"] == 1
    assert response.json()["created"] == 1
    assert response.json()["errors"] == [
        {"site": "unavailable", "message": "Lever retornou HTTP 503 para o site 'unavailable'."}
    ]
    stored = client.get("/api/jobs").json()
    assert len(stored) == 1
    assert stored[0]["sources"][0]["source"] == "lever"
    latest = client.get("/api/jobs/import-runs/latest").json()
    assert latest["status"] == "partial"
    assert latest["total"] == 1
    assert {source["status"] for source in latest["sources"]} == {"succeeded", "failed"}


def test_lever_import_requires_site_configuration_and_valid_region(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.jobs.get_lever_sites", lambda: [])
    assert client.post("/api/jobs/import-lever").status_code == 503

    monkeypatch.setattr("app.api.routes.jobs.get_lever_sites", lambda: ["company"])
    monkeypatch.setattr("app.api.routes.jobs.get_lever_region", lambda: "apac")
    response = client.post("/api/jobs/import-lever")
    assert response.status_code == 503
    assert "LEVER_REGION" in response.json()["detail"]


def test_lever_and_greenhouse_postings_are_deduplicated(client, monkeypatch):
    from app.schemas.jobs import NormalizedJob

    class FakeGreenhouseAdapter:
        source_name = "greenhouse"

        def __init__(self, board_token):
            self.board_token = board_token

        def fetch_jobs(self):
            return [
                NormalizedJob(
                    source="greenhouse",
                    external_id="acme:gh-301",
                    title="Backend Engineer",
                    company="Acme",
                    location="São Paulo, SP",
                    source_url="https://boards.greenhouse.io/acme/jobs/301",
                )
            ]

    class FakeLeverAdapter:
        def __init__(self, site, region):
            self.site = site
            self.region = region

        def fetch_jobs(self):
            return [
                NormalizedJob(
                    source="lever",
                    external_id="acme:lever-301",
                    title="BACKEND ENGINEER",
                    company="Acme",
                    location="Sao Paulo SP",
                    source_url="https://jobs.lever.co/acme/301",
                )
            ]

    monkeypatch.setattr("app.api.routes.jobs.get_greenhouse_board_tokens", lambda: ["acme"])
    monkeypatch.setattr("app.services.jobs.GreenhouseAdapter", FakeGreenhouseAdapter)
    assert client.post("/api/jobs/import-greenhouse").status_code == 200

    monkeypatch.setattr("app.api.routes.jobs.get_lever_sites", lambda: ["acme"])
    monkeypatch.setattr("app.api.routes.jobs.get_lever_region", lambda: "global")
    monkeypatch.setattr("app.services.jobs.LeverAdapter", FakeLeverAdapter)
    response = client.post("/api/jobs/import-lever")

    assert response.status_code == 200
    assert response.json()["created"] == 0
    assert response.json()["updated"] == 1
    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 1
    assert {source["source"] for source in jobs[0]["sources"]} == {"greenhouse", "lever"}


def test_import_from_different_sources_deduplicates_and_keeps_both_sources(client, monkeypatch):
    from app.schemas.jobs import NormalizedJob

    client.post("/api/jobs/import-fixture")

    class MatchingGreenhouseAdapter:
        source_name = "greenhouse"

        def __init__(self, board_token):
            self.board_token = board_token

        def fetch_jobs(self):
            return [
                NormalizedJob(
                    source="greenhouse",
                    external_id="company:201",
                    title="PESSOA Desenvolvedora Backend Junior",
                    company="Nuvem Clara",
                    location="Sao Paulo SP",
                    description="Descrição complementar da origem Greenhouse.",
                    source_url="https://boards.greenhouse.io/company/jobs/201",
                )
            ]

    monkeypatch.setattr("app.api.routes.jobs.get_greenhouse_board_tokens", lambda: ["company"])
    monkeypatch.setattr("app.services.jobs.GreenhouseAdapter", MatchingGreenhouseAdapter)

    result = client.post("/api/jobs/import-greenhouse")

    assert result.status_code == 200
    assert result.json()["created"] == 0
    assert result.json()["updated"] == 1
    assert result.json()["total"] == 1
    jobs = client.get("/api/jobs").json()
    matching = [job for job in jobs if job["title"] == "Pessoa Desenvolvedora Backend Júnior"]
    assert len(matching) == 1
    assert matching[0]["salary_min"] == 4500
    assert {source["source"] for source in matching[0]["sources"]} == {"fixture", "greenhouse"}
    assert {source["source_url"] for source in matching[0]["sources"]} == {
        "https://example.com/jobs/demo-001",
        "https://boards.greenhouse.io/company/jobs/201",
    }


def test_deduplication_keeps_different_locations_separate(client, monkeypatch):
    from app.schemas.jobs import NormalizedJob

    client.post("/api/jobs/import-fixture")

    class DifferentLocationAdapter:
        source_name = "greenhouse"

        def __init__(self, board_token):
            self.board_token = board_token

        def fetch_jobs(self):
            return [
                NormalizedJob(
                    source="greenhouse",
                    external_id="company:202",
                    title="Pessoa Desenvolvedora Backend Júnior",
                    company="Nuvem Clara",
                    location="Curitiba, PR",
                    source_url="https://boards.greenhouse.io/company/jobs/202",
                )
            ]

    monkeypatch.setattr("app.api.routes.jobs.get_greenhouse_board_tokens", lambda: ["company"])
    monkeypatch.setattr("app.services.jobs.GreenhouseAdapter", DifferentLocationAdapter)

    result = client.post("/api/jobs/import-greenhouse")

    assert result.status_code == 200
    assert result.json()["created"] == 1
    assert result.json()["updated"] == 0
    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 5


def test_reimport_merges_legacy_duplicate_records(client, monkeypatch):
    from sqlalchemy.orm import Session

    from app.main import engine
    from app.models import Job, JobSource
    from app.schemas.jobs import NormalizedJob

    with Session(engine) as db:
        db.add_all(
            [
                Job(
                    title="Backend Engineer",
                    company="Example Ltd",
                    description="",
                    location="São Paulo, SP",
                    status="open",
                    sources=[
                        JobSource(
                            source="greenhouse",
                            external_id="company:301",
                            source_url="https://boards.greenhouse.io/company/jobs/301",
                            original_payload={},
                        )
                    ],
                ),
                Job(
                    title="Backend Engineer",
                    company="Example Ltd",
                    description="Informação preservada do registro antigo.",
                    location="Sao Paulo SP",
                    status="open",
                    sources=[
                        JobSource(
                            source="legacy",
                            external_id="listing:301",
                            source_url="https://example.org/jobs/301",
                            original_payload={},
                        )
                    ],
                ),
            ]
        )
        db.commit()

    class ExistingGreenhouseAdapter:
        source_name = "greenhouse"

        def __init__(self, board_token):
            self.board_token = board_token

        def fetch_jobs(self):
            return [
                NormalizedJob(
                    source="greenhouse",
                    external_id="company:301",
                    title="Backend Engineer",
                    company="Example Ltd",
                    location="Sao Paulo SP",
                    source_url="https://boards.greenhouse.io/company/jobs/301",
                )
            ]

    monkeypatch.setattr("app.api.routes.jobs.get_greenhouse_board_tokens", lambda: ["company"])
    monkeypatch.setattr("app.services.jobs.GreenhouseAdapter", ExistingGreenhouseAdapter)

    result = client.post("/api/jobs/import-greenhouse")

    assert result.status_code == 200
    assert len(client.get("/api/jobs").json()) == 1
    merged_job = client.get("/api/jobs").json()[0]
    assert merged_job["description"] == "Informação preservada do registro antigo."
    assert {source["source"] for source in merged_job["sources"]} == {"greenhouse", "legacy"}


def test_deduplication_does_not_merge_two_ids_from_the_same_source(client, monkeypatch):
    from app.schemas.jobs import NormalizedJob

    client.post("/api/jobs/import-fixture")

    class MultipleGreenhouseListings:
        source_name = "greenhouse"

        def __init__(self, board_token):
            self.board_token = board_token

        def fetch_jobs(self):
            return [
                NormalizedJob(
                    source="greenhouse",
                    external_id=f"company:{self.board_token}",
                    title="Pessoa Desenvolvedora Backend Júnior",
                    company="Nuvem Clara",
                    location="São Paulo, SP",
                    source_url=f"https://boards.greenhouse.io/company/jobs/{self.board_token}",
                )
            ]

    monkeypatch.setattr("app.services.jobs.GreenhouseAdapter", MultipleGreenhouseListings)
    monkeypatch.setattr("app.api.routes.jobs.get_greenhouse_board_tokens", lambda: ["401", "402"])

    result = client.post("/api/jobs/import-greenhouse")

    assert result.status_code == 200
    assert result.json()["created"] == 1
    assert result.json()["updated"] == 1
    jobs = client.get("/api/jobs").json()
    matching = [job for job in jobs if job["title"] == "Pessoa Desenvolvedora Backend Júnior"]
    assert len(matching) == 2


def test_deduplication_leaves_ambiguous_matches_separate(client):
    from sqlalchemy.orm import Session

    from app.main import engine
    from app.models import Job, JobSource

    with Session(engine) as db:
        db.add_all(
            [
                Job(
                    title="Pessoa Desenvolvedora Backend Júnior",
                    company="Nuvem Clara",
                    description="",
                    location="São Paulo, SP",
                    status="open",
                    sources=[
                        JobSource(
                            source=source,
                            external_id=f"{source}:401",
                            source_url=f"https://{source}.example/jobs/401",
                            original_payload={},
                        )
                    ],
                )
                for source in ("source-a", "source-b")
            ]
        )
        db.commit()

    result = client.post("/api/jobs/import-fixture")

    assert result.status_code == 200
    assert result.json()["created"] == 4
    jobs = client.get("/api/jobs").json()
    matching = [job for job in jobs if job["title"] == "Pessoa Desenvolvedora Backend Júnior"]
    assert len(matching) == 3


def test_deduplication_preserves_discovery_metadata_and_consolidates_eligibility(client):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.main import engine
    from app.models import (
        DiscoveryQuery,
        ImportRun,
        ImportRunSource,
        Job,
        JobDiscovery,
        JobEligibility,
        JobSource,
    )
    from app.repositories.jobs import import_jobs
    from app.schemas.jobs import NormalizedJob

    earlier = datetime(2025, 1, 1, tzinfo=UTC)
    later = earlier + timedelta(days=1)
    with Session(engine) as db:
        run = ImportRun(requested_source="discovery", status="succeeded")
        canonical = Job(
            title="Backend Engineer", company="Example Ltd", location="São Paulo, SP", status="open",
            sources=[JobSource(source="greenhouse", external_id="acme:1", source_url="https://gh.example/1")],
        )
        duplicate = Job(
            title="BACKEND ENGINEER", company="Example Ltd", location="Sao Paulo SP", status="open",
            sources=[JobSource(source="remotive", external_id="remotive:1", source_url="https://remotive.com/1")],
        )
        run.sources = [
            ImportRunSource(source="remotive", scope="remote", status="succeeded"),
        ]
        db.add_all([run, canonical, duplicate])
        db.flush()
        remotive_query = DiscoveryQuery(
            import_run_source_id=run.sources[0].id, provider="remotive", strategy="remote",
            query_hash="a" * 64, search_terms="backend", location=None,
        )
        db.add(remotive_query)
        db.flush()
        db.add_all([
            JobDiscovery(job_id=duplicate.id, job_source_id=duplicate.sources[0].id,
                         query_id=remotive_query.id, discovered_at=earlier),
            JobDiscovery(job_id=canonical.id, job_source_id=canonical.sources[0].id,
                         query_id=remotive_query.id, discovered_at=later),
            JobEligibility(job_id=duplicate.id, status="eligible", reason="motivo antigo",
                           policy_version="v1", evaluated_at=earlier),
            JobEligibility(job_id=canonical.id, status="eligible", reason="motivo atual",
                           policy_version="v2", evaluated_at=later),
        ])
        db.commit()
        canonical_id, duplicate_id = canonical.id, duplicate.id

        import_jobs(db, [NormalizedJob(
            source="remotive", external_id="remotive:1", title="Backend Engineer", company="Example Ltd",
            location="São Paulo, SP", source_url="https://remotive.com/1",
        )])

        assert db.get(Job, duplicate_id) is None
        discoveries = list(db.scalars(select(JobDiscovery).order_by(JobDiscovery.id)).all())
        assert len(discoveries) == 2
        assert {item.job_id for item in discoveries} == {canonical_id}
        assert {item.job_source_id for item in discoveries} == {
            source.id for source in db.scalars(select(JobSource).where(JobSource.job_id == canonical_id))
        }
        eligibility = db.scalar(select(JobEligibility).where(JobEligibility.job_id == canonical_id))
        assert eligibility is not None
        assert eligibility.policy_version == "v2"
        assert eligibility.reason.startswith("motivo atual")
        assert "motivo antigo" in eligibility.reason
        assert "policy_version=v1" in eligibility.reason
        assert db.scalar(select(JobEligibility).where(JobEligibility.job_id == duplicate_id)) is None


def test_deduplication_merge_rolls_back_metadata_and_source_changes_on_failure(client):
    from datetime import UTC, datetime

    from sqlalchemy import event, select
    from sqlalchemy.orm import Session

    from app.main import engine
    from app.models import (
        DiscoveryQuery,
        ImportRun,
        ImportRunSource,
        Job,
        JobDiscovery,
        JobEligibility,
        JobSource,
    )
    from app.repositories.jobs import import_jobs
    from app.schemas.jobs import NormalizedJob

    with Session(engine) as db:
        canonical = Job(
            title="Backend Engineer", company="Example Ltd", location="São Paulo, SP", status="open",
            sources=[JobSource(source="greenhouse", external_id="acme:2", source_url="https://gh.example/2")],
        )
        duplicate = Job(
            title="BACKEND ENGINEER", company="Example Ltd", location="Sao Paulo SP", status="open",
            sources=[JobSource(source="remotive", external_id="remotive:2", source_url="https://remotive.com/2")],
        )
        db.add_all([canonical, duplicate])
        db.flush()
        source_id, duplicate_id, canonical_id = duplicate.sources[0].id, duplicate.id, canonical.id
        run = ImportRun(requested_source="discovery", status="succeeded")
        run_source = ImportRunSource(source="remotive", scope="remote", status="succeeded")
        run.sources.append(run_source)
        db.add(run)
        db.flush()
        query = DiscoveryQuery(
            import_run_source_id=run_source.id,
            provider="remotive",
            strategy="remote",
            query_hash="c" * 64,
            search_terms="backend",
        )
        db.add(query)
        db.flush()
        db.add_all([
            JobDiscovery(job_id=duplicate.id, job_source_id=source_id, query_id=query.id,
                         discovered_at=datetime(2025, 1, 1, tzinfo=UTC)),
            JobEligibility(
                job_id=duplicate.id,
                reason="saved",
                evaluated_at=datetime(2025, 1, 1, tzinfo=UTC),
            ),
        ])
        db.commit()

        def fail_after_merge(session, flush_context, instances):
            if session.info.pop("fail_merge_flush", False):
                raise RuntimeError("simulated flush failure")

        event.listen(Session, "before_flush", fail_after_merge)
        try:
            db.info["fail_merge_flush"] = True
            try:
                import_jobs(
                    db,
                    [NormalizedJob(
                        source="remotive",
                        external_id="remotive:2",
                        title="Backend Engineer",
                        company="Example Ltd",
                        location="São Paulo, SP",
                        source_url="https://remotive.com/2",
                    )],
                    commit=False,
                    new_job_ids=set(),
                )
            except RuntimeError as exc:
                assert str(exc) == "simulated flush failure"
            else:
                raise AssertionError("expected simulated flush failure")
            db.rollback()
        finally:
            event.remove(Session, "before_flush", fail_after_merge)

    with Session(engine) as verify:
        assert verify.get(Job, duplicate_id) is not None
        assert verify.scalar(select(JobSource.job_id).where(JobSource.id == source_id)) == duplicate_id
        assert (
            verify.scalar(select(JobDiscovery.job_id).where(JobDiscovery.job_source_id == source_id))
            == duplicate_id
        )
        assert (
            verify.scalar(select(JobEligibility.job_id).where(JobEligibility.job_id == duplicate_id))
            == duplicate_id
        )
        assert verify.get(Job, canonical_id) is not None


def test_source_listing_closes_after_two_complete_absences_and_reopens(client, monkeypatch):
    from app.adapters.greenhouse import GreenhouseSourceError
    from app.schemas.jobs import NormalizedJob

    class SequencedAdapter:
        attempts = 0

        def __init__(self, board_token):
            self.board_token = board_token

        def fetch_jobs(self):
            type(self).attempts += 1
            if type(self).attempts in (1, 5):
                return [
                    NormalizedJob(
                        source="greenhouse",
                        external_id="acme:job-1",
                        title="Backend Developer",
                        company="Acme",
                        source_url="https://boards.greenhouse.io/acme/jobs/1",
                    )
                ]
            if type(self).attempts == 2:
                raise GreenhouseSourceError("Falha temporária.")
            return []

    monkeypatch.setattr("app.api.routes.jobs.get_greenhouse_board_tokens", lambda: ["acme"])
    monkeypatch.setattr("app.services.jobs.GreenhouseAdapter", SequencedAdapter)

    assert client.post("/api/jobs/import-greenhouse").json()["boards_succeeded"] == 1
    assert client.get("/api/jobs").json()[0]["status"] == "open"

    failed = client.post("/api/jobs/import-greenhouse").json()
    assert len(failed["errors"]) == 1
    assert client.get("/api/jobs").json()[0]["status"] == "open"

    client.post("/api/jobs/import-greenhouse")
    assert client.get("/api/jobs").json()[0]["status"] == "open"

    client.post("/api/jobs/import-greenhouse")
    assert client.get("/api/jobs").json()[0]["status"] == "closed"

    client.post("/api/jobs/import-greenhouse")
    assert client.get("/api/jobs").json()[0]["status"] == "open"


def test_job_remains_open_until_all_monitored_sources_confirm_absence(client, monkeypatch):
    from app.schemas.jobs import NormalizedJob

    class FakeGreenhouse:
        attempts = 0

        def __init__(self, board_token):
            pass

        def fetch_jobs(self):
            type(self).attempts += 1
            if type(self).attempts == 1:
                return [
                    NormalizedJob(
                        source="greenhouse",
                        external_id="acme:gh-1",
                        title="Backend Engineer",
                        company="Acme",
                        location="São Paulo",
                        source_url="https://boards.greenhouse.io/acme/jobs/1",
                    )
                ]
            return []

    class FakeLever:
        attempts = 0

        def __init__(self, site, region):
            pass

        def fetch_jobs(self):
            type(self).attempts += 1
            if type(self).attempts == 1:
                return [
                    NormalizedJob(
                        source="lever",
                        external_id="acme:lever-1",
                        title="Backend Engineer",
                        company="Acme",
                        location="Sao Paulo",
                        source_url="https://jobs.lever.co/acme/1",
                    )
                ]
            return []

    monkeypatch.setattr("app.api.routes.jobs.get_greenhouse_board_tokens", lambda: ["acme"])
    monkeypatch.setattr("app.services.jobs.GreenhouseAdapter", FakeGreenhouse)
    monkeypatch.setattr("app.api.routes.jobs.get_lever_sites", lambda: ["acme"])
    monkeypatch.setattr("app.api.routes.jobs.get_lever_region", lambda: "global")
    monkeypatch.setattr("app.services.jobs.LeverAdapter", FakeLever)

    client.post("/api/jobs/import-greenhouse")
    client.post("/api/jobs/import-lever")
    assert len(client.get("/api/jobs").json()) == 1

    client.post("/api/jobs/import-greenhouse")
    client.post("/api/jobs/import-greenhouse")
    assert client.get("/api/jobs").json()[0]["status"] == "open"

    client.post("/api/jobs/import-lever")
    assert client.get("/api/jobs").json()[0]["status"] == "open"
    client.post("/api/jobs/import-lever")
    assert client.get("/api/jobs").json()[0]["status"] == "closed"


def test_next_run_marks_abandoned_running_run_as_interrupted(client, monkeypatch):
    from sqlalchemy.orm import Session

    from app.main import engine
    from app.models import ImportRun, ImportRunSource

    with Session(engine) as db:
        abandoned = ImportRun(
            requested_source="all",
            status="running",
            sources=[ImportRunSource(source="greenhouse", scope="acme", status="pending")],
        )
        db.add(abandoned)
        db.commit()
        abandoned_id = abandoned.id

    class EmptyAdapter:
        def __init__(self, board_token):
            pass

        def fetch_jobs(self):
            return []

    monkeypatch.setattr("app.api.routes.jobs.get_greenhouse_board_tokens", lambda: ["acme"])
    monkeypatch.setattr("app.services.jobs.GreenhouseAdapter", EmptyAdapter)
    response = client.post("/api/jobs/import-greenhouse")
    assert response.status_code == 200

    with Session(engine) as db:
        interrupted = db.get(ImportRun, abandoned_id)
        assert interrupted.status == "interrupted"
        assert interrupted.sources[0].status == "failed"
