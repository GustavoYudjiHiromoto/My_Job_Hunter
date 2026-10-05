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
