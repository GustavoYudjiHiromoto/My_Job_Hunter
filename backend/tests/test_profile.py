def test_profile_is_created_and_updated(client):
    initial = client.get("/api/profile")
    assert initial.status_code == 200
    assert initial.json()["full_name"] == ""

    updated = client.put("/api/profile", json={"full_name": "Ana Silva", "skills": "Python\\nFastAPI"})
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Ana Silva"
    assert updated.json()["skills"] == "Python\\nFastAPI"


def test_experience_crud_and_date_validation(client):
    created = client.post(
        "/api/profile/experiences",
        json={"company": "Acme", "role": "Dev", "start_date": "2022-01-01", "is_current": True},
    )
    assert created.status_code == 201
    experience_id = created.json()["id"]
    assert client.get("/api/profile").json()["experiences"][0]["company"] == "Acme"

    invalid = client.put(
        f"/api/profile/experiences/{experience_id}",
        json={"company": "Acme", "role": "Dev", "is_current": True, "end_date": "2025-01-01"},
    )
    assert invalid.status_code == 422
    assert client.delete(f"/api/profile/experiences/{experience_id}").status_code == 204
    assert client.delete(f"/api/profile/experiences/{experience_id}").status_code == 404


def test_education_and_preference_are_persisted(client):
    education = client.post(
        "/api/profile/education",
        json={"institution": "Universidade", "degree": "Bacharelado", "field_of_study": "Computação"},
    )
    assert education.status_code == 201
    assert education.json()["institution"] == "Universidade"

    preference = client.put(
        "/api/profile/preferences",
        json={"desired_titles": "Backend Engineer", "minimum_salary": 5000, "maximum_salary": 9000},
    )
    assert preference.status_code == 200
    profile = client.get("/api/profile").json()
    assert profile["education"][0]["degree"] == "Bacharelado"
    assert profile["preference"]["minimum_salary"] == 5000


def test_preference_rejects_inverted_salary_range(client):
    response = client.put(
        "/api/profile/preferences",
        json={"minimum_salary": 10000, "maximum_salary": 5000},
    )
    assert response.status_code == 422
