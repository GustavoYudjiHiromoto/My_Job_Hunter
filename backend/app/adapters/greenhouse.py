import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from app.adapters.base import JobAdapter
from app.schemas.jobs import NormalizedJob

API_ROOT = "https://boards-api.greenhouse.io/v1/boards"
BOARD_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class GreenhouseSourceError(RuntimeError):
    """Erro seguro e legível ao consultar um board público Greenhouse."""


class _DescriptionTextParser(HTMLParser):
    BLOCK_TAGS = {"br", "div", "li", "p", "section", "tr"}
    HIDDEN_TAGS = {"script", "style"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.HIDDEN_TAGS:
            self.hidden_depth += 1
        elif tag in self.BLOCK_TAGS and self.hidden_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.HIDDEN_TAGS and self.hidden_depth:
            self.hidden_depth -= 1
        elif tag in self.BLOCK_TAGS and self.hidden_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.hidden_depth == 0:
            self.parts.append(data)


def description_to_text(content: str) -> str:
    # Greenhouse pode retornar conteúdo HTML com entidades escapadas mais de uma vez.
    for _ in range(3):
        decoded = unescape(content)
        if decoded == content:
            break
        content = decoded

    parser = _DescriptionTextParser()
    parser.feed(content)
    parser.close()
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


class GreenhouseAdapter(JobAdapter):
    source_name = "greenhouse"

    def __init__(self, board_token: str, client: httpx.Client | None = None):
        if len(board_token) > 120 or not BOARD_TOKEN_PATTERN.fullmatch(board_token):
            raise GreenhouseSourceError("O identificador do board Greenhouse contém caracteres inválidos.")
        self.board_token = board_token
        self.client = client

    def fetch_jobs(self) -> list[NormalizedJob]:
        if self.client is not None:
            return self._fetch_jobs(self.client)

        try:
            with httpx.Client(timeout=15.0, follow_redirects=False) as client:
                return self._fetch_jobs(client)
        except httpx.HTTPError as error:
            raise GreenhouseSourceError(
                f"Falha de conexão ao consultar o board Greenhouse '{self.board_token}'."
            ) from error

    def _get_json(self, client: httpx.Client, path: str, params: dict[str, str] | None = None) -> Any:
        url = f"{API_ROOT}/{quote(self.board_token, safe='')}"
        if path:
            url = f"{url}/{path}"
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError as error:
            raise GreenhouseSourceError(
                f"Falha de conexão ao consultar o board Greenhouse '{self.board_token}'."
            ) from error

        if not 200 <= response.status_code < 300:
            raise GreenhouseSourceError(
                f"Greenhouse retornou HTTP {response.status_code} para o board '{self.board_token}'."
            )
        try:
            return response.json()
        except ValueError as error:
            raise GreenhouseSourceError(
                f"Greenhouse retornou JSON inválido para o board '{self.board_token}'."
            ) from error

    def _fetch_jobs(self, client: httpx.Client) -> list[NormalizedJob]:
        board = self._get_json(client, "")
        if not isinstance(board, dict) or not isinstance(board.get("name"), str) or not board["name"].strip():
            raise GreenhouseSourceError(
                f"Greenhouse não informou o nome da empresa no board '{self.board_token}'."
            )

        response = self._get_json(client, "jobs", params={"content": "true"})
        if not isinstance(response, dict) or not isinstance(response.get("jobs"), list):
            raise GreenhouseSourceError(
                f"Greenhouse retornou uma lista de vagas inválida para o board '{self.board_token}'."
            )

        jobs: list[NormalizedJob] = []
        for record in response["jobs"]:
            if not isinstance(record, dict):
                raise GreenhouseSourceError(
                    f"Greenhouse retornou uma vaga inválida no board '{self.board_token}'."
                )
            # Prospect posts são formulários genéricos, não vagas publicadas.
            if "internal_job_id" in record and record["internal_job_id"] is None:
                continue

            greenhouse_id = record.get("id")
            title = record.get("title")
            source_url = record.get("absolute_url")
            if greenhouse_id is None or not isinstance(title, str) or not title.strip() or not source_url:
                raise GreenhouseSourceError(
                    f"Greenhouse retornou uma vaga sem identificador, título ou "
                    f"URL no board '{self.board_token}'."
                )

            location_data = record.get("location")
            location = location_data.get("name") if isinstance(location_data, dict) else None
            if not isinstance(location, str) or not location.strip():
                location = None

            raw_description = record.get("content") or ""
            company = record.get("company_name")
            if not isinstance(company, str) or not company.strip():
                company = board["name"]
            try:
                job = NormalizedJob(
                    source=self.source_name,
                    external_id=f"{self.board_token}:{greenhouse_id}",
                    title=title.strip(),
                    company=company.strip(),
                    description=description_to_text(raw_description)
                    if isinstance(raw_description, str)
                    else "",
                    location=location,
                    # A listagem pública não garante senioridade, modalidade ou remuneração.
                    workplace_type=None,
                    seniority=None,
                    employment_type=None,
                    salary_min=None,
                    salary_max=None,
                    salary_currency=None,
                    published_at=record.get("first_published"),
                    status="open",
                    source_url=source_url,
                    original_payload=record,
                )
            except ValidationError as error:
                raise GreenhouseSourceError(
                    f"Greenhouse retornou dados inválidos para uma vaga do board '{self.board_token}'."
                ) from error
            jobs.append(job)
        return jobs
