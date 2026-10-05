from app.adapters.greenhouse import GreenhouseSourceError
from app.schemas.jobs import NormalizedJob


class FakeEmailNotifier:
    def __init__(self, fails=False):
        self.messages = []
        self.fails = fails

    def send_email(self, recipient, subject, body):
        if self.fails:
            raise RuntimeError("fake delivery failure")
        self.messages.append((recipient, subject, body))


def configure_alerts(client, minimum_score=0):
    return client.put(
        "/api/notifications/settings",
        json={"enabled": True, "recipient_email": "candidate@example.com", "minimum_score": minimum_score},
    )


def test_notification_settings_require_email_and_threshold_when_enabled(client):
    invalid_email = client.put(
        "/api/notifications/settings",
        json={"enabled": True, "recipient_email": "invalid", "minimum_score": 70},
    )
    missing_score = client.put(
        "/api/notifications/settings",
        json={"enabled": True, "recipient_email": "candidate@example.com", "minimum_score": None},
    )

    assert invalid_email.status_code == 422
    assert missing_score.status_code == 422
    settings = client.get("/api/notifications/settings")
    assert settings.status_code == 200
    assert settings.json() == {
        "enabled": False,
        "recipient_email": "",
        "minimum_score": None,
        "smtp_configured": False,
    }


def test_new_jobs_are_emailed_once_and_history_is_persisted(client, monkeypatch):
    notifier = FakeEmailNotifier()
    monkeypatch.setattr("app.services.notifications.create_email_notifier", lambda: notifier)

    class FakeGreenhouseAdapter:
        def __init__(self, board_token):
            self.board_token = board_token

        def fetch_jobs(self):
            return [
                NormalizedJob(
                    source="greenhouse",
                    external_id=f"{self.board_token}:job-1",
                    title="Backend Engineer",
                    company="Example",
                    description="Python API",
                    source_url="https://boards.greenhouse.io/example/jobs/job-1",
                )
            ]

    monkeypatch.setattr("app.services.jobs.GreenhouseAdapter", FakeGreenhouseAdapter)
    monkeypatch.setattr("app.api.routes.jobs.get_greenhouse_board_tokens", lambda: ["example"])
    assert configure_alerts(client).status_code == 200

    first = client.post("/api/jobs/import-greenhouse")
    second = client.post("/api/jobs/import-greenhouse")

    assert first.status_code == second.status_code == 200
    assert len(notifier.messages) == 1
    assert "Backend Engineer" in notifier.messages[0][2]
    history = client.get("/api/notifications").json()
    assert len(history) == 1
    assert history[0]["status"] == "sent"
    assert history[0]["jobs"][0]["title"] == "Backend Engineer"


def test_partial_import_notifies_successful_source_and_fake_failure_does_not_fail_run(client, monkeypatch):
    notifier = FakeEmailNotifier(fails=True)
    monkeypatch.setattr("app.services.notifications.create_email_notifier", lambda: notifier)

    class FakeGreenhouseAdapter:
        def __init__(self, board_token):
            self.board_token = board_token

        def fetch_jobs(self):
            if self.board_token == "broken":
                raise GreenhouseSourceError("HTTP 503")
            return [
                NormalizedJob(
                    source="greenhouse",
                    external_id="good:job-1",
                    title="Backend Engineer",
                    company="Example",
                    source_url="https://boards.greenhouse.io/example/jobs/job-1",
                )
            ]

    monkeypatch.setattr("app.services.jobs.GreenhouseAdapter", FakeGreenhouseAdapter)
    monkeypatch.setattr("app.api.routes.jobs.get_greenhouse_board_tokens", lambda: ["good", "broken"])
    assert configure_alerts(client).status_code == 200

    response = client.post("/api/jobs/import-greenhouse")

    assert response.status_code == 200
    latest = client.get("/api/jobs/import-runs/latest").json()
    assert latest["status"] == "partial"
    history = client.get("/api/notifications").json()
    assert len(history) == 1
    assert history[0]["status"] == "failed"
    assert history[0]["error"] == "Não foi possível enviar o e-mail."
    assert notifier.messages == []
