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
