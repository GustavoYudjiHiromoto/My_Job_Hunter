import json
from pathlib import Path
from typing import Any

from app.schemas.jobs import NormalizedJob

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "jobs.json"


class FixtureAdapter:
    source_name = "fixture"

    def __init__(self, fixture_path: Path = FIXTURE_PATH):
        self.fixture_path = fixture_path

    def fetch_jobs(self) -> list[NormalizedJob]:
        with self.fixture_path.open(encoding="utf-8") as fixture_file:
            records: list[dict[str, Any]] = json.load(fixture_file)
        return [NormalizedJob.model_validate({**record, "source": self.source_name}) for record in records]
