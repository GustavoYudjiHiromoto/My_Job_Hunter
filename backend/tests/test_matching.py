def test_recommendations_rank_jobs_and_explain_criteria(client):
    client.put(
        "/api/profile",
        json={"skills": "Python, SQL", "professional_summary": "Desenvolvedora backend"},
    )
    client.put(
        "/api/profile/preferences",
        json={
            "desired_titles": "Pessoa Desenvolvedora Backend Júnior",
            "desired_locations": "São Paulo",
            "work_modes": "Híbrido",
            "seniority": "Júnior",
            "employment_types": "CLT",
            "minimum_salary": 4000,
            "maximum_salary": 7000,
            "salary_currency": "BRL",
            "must_have": "Python",
            "excluded_criteria": "presencial",
        },
    )
    client.post("/api/jobs/import-fixture")

    response = client.get("/api/jobs/recommendations")

    assert response.status_code == 200
    recommendations = response.json()
    assert recommendations[0]["job"]["title"] == "Pessoa Desenvolvedora Backend Júnior"
    assert recommendations[0]["score"] > recommendations[1]["score"]
    assert recommendations[0]["coverage"] == 100
    assert "Python" in " ".join(recommendations[0]["strengths"])
    assert "SQL" not in " ".join(recommendations[0]["gaps"])
    assert any(
        item["key"] == "salary" and item["result"] == "match" for item in recommendations[0]["criteria"]
    )
    assert all(item["job"]["status"] == "open" for item in recommendations)


def test_recommendation_filters_location_score_and_exclusions(client):
    client.put(
        "/api/profile/preferences",
        json={"excluded_criteria": "presencial"},
    )
    client.post("/api/jobs/import-fixture")

    response = client.get(
        "/api/jobs/recommendations",
        params={"location": "São Paulo", "min_score": 0, "include_excluded": "false"},
    )

    assert response.status_code == 200
    recommendations = response.json()
    assert len(recommendations) == 1
    assert recommendations[0]["job"]["location"] == "São Paulo, SP"
    assert not recommendations[0]["excluded"]

    with_excluded = client.get("/api/jobs/recommendations", params={"status": "all"}).json()
    excluded = [item for item in with_excluded if item["excluded"]]
    assert len(excluded) == 1
    assert excluded[0]["score"] == 0
    assert any("presencial" in gap.casefold() for gap in excluded[0]["gaps"])


def test_empty_profile_marks_criteria_unknown_with_zero_coverage(client):
    client.post("/api/jobs/import-fixture")

    response = client.get("/api/jobs/recommendations")

    assert response.status_code == 200
    assert response.json()
    assert all(item["score"] == 0 and item["coverage"] == 0 for item in response.json())
    assert all(
        all(criterion["result"] == "unknown" for criterion in item["criteria"]) for item in response.json()
    )


def test_recommendation_filters_validate_score_and_location(client):
    assert client.get("/api/jobs/recommendations", params={"min_score": 101}).status_code == 422
    assert client.get("/api/jobs/recommendations", params={"location": ""}).status_code == 422


def test_recommendation_filter_matches_normalized_work_mode(client):
    client.post("/api/jobs/import-fixture")

    response = client.get(
        "/api/jobs/recommendations",
        params={"workplace_type": "remote", "status": "all"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["job"]["workplace_type"] == "Remoto"


def test_partial_salary_range_is_uncertain_instead_of_a_mismatch(client):
    from sqlalchemy.orm import Session

    from app.main import engine
    from app.models import Job, JobSource, Preference, ProfessionalProfile
    from app.services.matching import analyze_job

    with Session(engine) as db:
        profile = ProfessionalProfile(
            preference=Preference(minimum_salary=7000, maximum_salary=None, salary_currency="BRL")
        )
        job = Job(
            title="Desenvolvedora",
            company="Exemplo",
            description="",
            salary_min=5000,
            salary_max=None,
            salary_currency="BRL",
            status="open",
            sources=[
                JobSource(
                    source="test",
                    external_id="salary-partial",
                    source_url="https://example.com/jobs/salary-partial",
                    original_payload={},
                )
            ],
        )
        db.add_all([profile, job])
        db.commit()
        recommendation = analyze_job(job, profile)
    salary = next(item for item in recommendation.criteria if item.key == "salary")

    assert salary.result == "partial"
    assert salary.points == 5
    assert recommendation.coverage == 5
