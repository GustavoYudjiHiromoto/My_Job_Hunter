import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from app.adapters.base import JobAdapter
from app.schemas.jobs import NormalizedJob

API_ROOTS = {
    "global": "https://api.lever.co/v0/postings",
    "eu": "https://api.eu.lever.co/v0/postings",
}
SITE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
PAGE_SIZE = 100


class LeverSourceError(RuntimeError):
    """Erro seguro e legível ao consultar a API pública de postings do Lever."""


class _PlainTextParser(HTMLParser):
    BLOCK_TAGS = {"br", "div", "li", "p", "section", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _html_to_text(content: str) -> str:
    parser = _PlainTextParser()
    parser.feed(content)
    parser.close()
    return "\n".join(line.strip() for line in "".join(parser.parts).strip().splitlines() if line.strip())


def _description(record: dict[str, Any]) -> str:
    parts: list[str] = []
    full_description = record.get("descriptionPlain")
    if isinstance(full_description, str) and full_description.strip():
        parts.append(full_description.strip())
    else:
        for field in ("openingPlain", "descriptionBodyPlain"):
            value = record.get(field)
            if isinstance(value, str) and value.strip() and value.strip() not in parts:
                parts.append(value.strip())
    additional = record.get("additionalPlain")
    if isinstance(additional, str) and additional.strip():
        parts.append(additional.strip())

    lists = record.get("lists")
    if isinstance(lists, list):
        for item in lists:
            if not isinstance(item, dict):
                continue
            label = item.get("text")
            content = item.get("content")
            plain_content = _html_to_text(content) if isinstance(content, str) else ""
            if isinstance(label, str) and label.strip():
                parts.append(label.strip())
            if plain_content:
                parts.append(plain_content)
    return "\n\n".join(parts)


def _published_at(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        except ValueError:
            return None
    return None


def _location(categories: dict[str, Any]) -> str | None:
    primary = categories.get("location")
    if isinstance(primary, str) and primary.strip():
        return primary.strip()
    all_locations = categories.get("allLocations")
    if isinstance(all_locations, list):
        values = [value.strip() for value in all_locations if isinstance(value, str) and value.strip()]
        if values:
            return "; ".join(values)
    return None


class LeverAdapter(JobAdapter):
    source_name = "lever"

    def __init__(
        self,
        site: str,
        region: str = "global",
        client: httpx.Client | None = None,
        page_size: int = PAGE_SIZE,
    ):
        if len(site) > 120 or not SITE_PATTERN.fullmatch(site):
            raise LeverSourceError("O identificador do site Lever contém caracteres inválidos.")
        if region not in API_ROOTS:
            raise LeverSourceError("A região Lever deve ser global ou eu.")
        if page_size < 1 or page_size > 1000:
            raise LeverSourceError("O tamanho de página Lever deve estar entre 1 e 1000.")
        self.site = site
        self.region = region
        self.client = client
        self.page_size = page_size

    def fetch_jobs(self) -> list[NormalizedJob]:
        if self.client is not None:
            return self._fetch_jobs(self.client)
        try:
            with httpx.Client(timeout=15.0, follow_redirects=False) as client:
                return self._fetch_jobs(client)
        except httpx.HTTPError as error:
            raise LeverSourceError(f"Falha de conexão ao consultar o site Lever '{self.site}'.") from error

    def _get_page(self, client: httpx.Client, skip: int) -> Any:
        url = f"{API_ROOTS[self.region]}/{quote(self.site, safe='')}"
        try:
            response = client.get(
                url,
                params={"mode": "json", "skip": str(skip), "limit": str(self.page_size)},
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as error:
            raise LeverSourceError(f"Falha de conexão ao consultar o site Lever '{self.site}'.") from error
        if not 200 <= response.status_code < 300:
            raise LeverSourceError(f"Lever retornou HTTP {response.status_code} para o site '{self.site}'.")
        try:
            payload = response.json()
        except ValueError as error:
            raise LeverSourceError(f"Lever retornou JSON inválido para o site '{self.site}'.") from error
        if not isinstance(payload, list):
            raise LeverSourceError(
                f"Lever retornou uma lista de postings inválida para o site '{self.site}'."
            )
        return payload

    def _fetch_jobs(self, client: httpx.Client) -> list[NormalizedJob]:
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        skip = 0
        while True:
            page = self._get_page(client, skip)
            if not page:
                break
            new_records = []
            for record in page:
                if not isinstance(record, dict):
                    raise LeverSourceError(f"Lever retornou um posting inválido para o site '{self.site}'.")
                posting_id = record.get("id")
                if posting_id is None:
                    raise LeverSourceError(f"Lever retornou um posting sem ID para o site '{self.site}'.")
                posting_id = str(posting_id)
                if posting_id not in seen_ids:
                    seen_ids.add(posting_id)
                    new_records.append(record)
            if len(page) >= self.page_size and not new_records:
                raise LeverSourceError(f"Paginação repetida ao consultar o site Lever '{self.site}'.")
            records.extend(new_records)
            if len(page) < self.page_size:
                break
            skip += len(page)

        return [self._normalize(record) for record in records]

    def _normalize(self, record: dict[str, Any]) -> NormalizedJob:
        posting_id = str(record["id"])
        title = record.get("text")
        hosted_url = record.get("hostedUrl")
        if not isinstance(title, str) or not title.strip():
            raise LeverSourceError(f"Lever retornou um posting sem título para o site '{self.site}'.")
        if not isinstance(hosted_url, str) or not hosted_url.strip():
            hostname = "jobs.eu.lever.co" if self.region == "eu" else "jobs.lever.co"
            hosted_url = f"https://{hostname}/{quote(self.site, safe='')}/{quote(posting_id, safe='')}"

        categories = record.get("categories")
        if not isinstance(categories, dict):
            categories = {}
        workplace = record.get("workplaceType")
        workplace_map = {
            "remote": "Remoto",
            "hybrid": "Híbrido",
            "on-site": "Presencial",
            "onsite": "Presencial",
        }
        workplace_type = workplace_map.get(workplace.casefold()) if isinstance(workplace, str) else None
        commitment = categories.get("commitment")
        employment_type = commitment.strip() if isinstance(commitment, str) and commitment.strip() else None
        try:
            return NormalizedJob(
                source=self.source_name,
                external_id=f"{self.site}:{posting_id}",
                title=title.strip(),
                company=self.site.replace("-", " ").replace("_", " ").title(),
                description=_description(record),
                location=_location(categories),
                workplace_type=workplace_type,
                seniority=record.get("level") if isinstance(record.get("level"), str) else None,
                employment_type=employment_type,
                # A faixa Lever inclui intervalos como anual ou por hora. O modelo atual
                # não armazena esse intervalo; não comparar quantias incomparáveis.
                salary_min=None,
                salary_max=None,
                salary_currency=None,
                published_at=_published_at(record.get("createdAt")),
                status="open",
                source_url=hosted_url,
                original_payload=record,
            )
        except ValidationError as error:
            raise LeverSourceError(
                f"Lever retornou dados inválidos para um posting do site '{self.site}'."
            ) from error
