import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import get_jsearch_api_key
from app.schemas.jobs import NormalizedJob

JSEARCH_ROOT = "https://api.openwebninja.com/jsearch/search-v2"
REMOTIVE_ROOT = "https://remotive.com/api/remote-jobs"
JOBICY_ROOT = "https://jobicy.com/api/v2/remote-jobs"


class DiscoveryProviderError(RuntimeError):
    """Falha de provider apresentada sem revelar credenciais ou query secrets."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        diagnostic: "NormalizationDiagnostic | None" = None,
    ):
        super().__init__(message)
        self.http_status = http_status
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class NormalizationIssue:
    loc: tuple[str | int, ...]
    error_type: str


@dataclass(frozen=True)
class NormalizationDiagnostic:
    stage: str
    exception_type: str
    code: str | None = None
    fields: tuple[str, ...] = ()
    issues: tuple[NormalizationIssue, ...] = ()
    record_index: int | None = None


class _JSearchNormalizationError(ValueError):
    def __init__(self, message: str, *, code: str, fields: tuple[str, ...]):
        super().__init__(message)
        self.code = code
        self.fields = fields


def _jsearch_normalization_diagnostic(
    error: Exception, *, record_index: int
) -> NormalizationDiagnostic:
    if isinstance(error, ValidationError):
        issues = tuple(
            NormalizationIssue(
                loc=tuple(part for part in issue.get("loc", ()) if isinstance(part, (str, int))),
                error_type=issue.get("type", "validation_error"),
            )
            for issue in error.errors(include_input=False)
        )
        return NormalizationDiagnostic(
            stage="normalize_record",
            exception_type=type(error).__name__,
            issues=issues,
            record_index=record_index,
        )
    if isinstance(error, _JSearchNormalizationError):
        return NormalizationDiagnostic(
            stage="normalize_record",
            exception_type=type(error).__name__,
            code=error.code,
            fields=error.fields,
            record_index=record_index,
        )
    return NormalizationDiagnostic(
        stage="normalize_record",
        exception_type=type(error).__name__,
        code="normalization_error",
        record_index=record_index,
    )


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _plain_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    parser = _TextExtractor()
    parser.feed(value)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _number(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return int(value)
    return None


def _jsearch_external_id(value: Any) -> str:
    """Keep provider IDs intact unless they exceed the shared 200-char limit."""
    external_id = str(value)
    if len(external_id) <= 200:
        return external_id
    digest = hashlib.sha256(external_id.encode("utf-8")).hexdigest()
    return f"jsearch-sha256:{digest}"


class JSearchDiscoveryAdapter:
    source_name = "jsearch"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client

    @staticmethod
    def is_configured() -> bool:
        return bool(get_jsearch_api_key())

    def search(
        self, query: str, *, work_from_home: bool = False, limit: int = 25
    ) -> list[NormalizedJob]:
        query = " ".join(query.split())
        if not query:
            raise DiscoveryProviderError("Informe termos para pesquisar no JSearch.")
        api_key = get_jsearch_api_key()
        if not api_key:
            raise DiscoveryProviderError("Configure JSEARCH_API_KEY para habilitar o JSearch.")
        params = {
            "query": query,
            "country": "br",
            "language": "pt",
            "work_from_home": str(work_from_home).lower(),
        }
        try:
            response = self._get(params, api_key)
        except httpx.HTTPError as error:
            raise DiscoveryProviderError("Falha de conexão ao consultar JSearch.") from error
        if not 200 <= response.status_code < 300:
            raise DiscoveryProviderError(
                f"JSearch retornou HTTP {response.status_code}.", http_status=response.status_code
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise DiscoveryProviderError("JSearch retornou JSON inválido.") from error
        data = payload.get("data") if isinstance(payload, dict) else None
        records = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(records, list):
            raise DiscoveryProviderError("JSearch retornou uma lista de resultados inválida.")
        normalized = []
        for index, record in enumerate(records[:limit]):
            if not isinstance(record, dict):
                diagnostic = NormalizationDiagnostic(
                    stage="normalize_record",
                    exception_type="TypeError",
                    code="record_not_object",
                    fields=("data.jobs",),
                    record_index=index,
                )
                raise DiscoveryProviderError(
                    "JSearch retornou dados de vaga inválidos.", diagnostic=diagnostic
                ) from None
            try:
                normalized.append(self._normalize(record))
            except (ValidationError, KeyError, TypeError, ValueError) as error:
                diagnostic = _jsearch_normalization_diagnostic(error, record_index=index)
                raise DiscoveryProviderError(
                    "JSearch retornou dados de vaga inválidos.", diagnostic=diagnostic
                ) from None
        return normalized

    def _get(self, params: dict[str, Any], api_key: str) -> httpx.Response:
        headers = {"Accept": "application/json", "x-api-key": api_key}
        if self.client is not None:
            return self.client.get(JSEARCH_ROOT, params=params, headers=headers)
        with httpx.Client(timeout=20.0, follow_redirects=False) as client:
            return client.get(JSEARCH_ROOT, params=params, headers=headers)

    def _normalize(self, record: dict[str, Any]) -> NormalizedJob:
        title = record.get("job_title")
        company = record.get("employer_name")
        external_id = record.get("job_id") or record.get("job_uid")
        url = record.get("job_apply_link")
        url_field = "job_apply_link"
        if not isinstance(url, str) or not url.strip():
            url_field = "apply_options"
            options = record.get("apply_options")
            if isinstance(options, list):
                url = next(
                    (item.get("apply_link") for item in options
                     if isinstance(item, dict) and isinstance(item.get("apply_link"), str)
                     and item["apply_link"].strip()),
                    None,
                )
        missing_fields = tuple(
            field
            for field, value in (
                ("job_title", title),
                ("employer_name", company),
                (url_field, url),
            )
            if not isinstance(value, str) or not value.strip()
        )
        if missing_fields:
            raise _JSearchNormalizationError(
                "Required JSearch fields missing",
                code="required_fields_missing",
                fields=missing_fields,
            )
        if external_id is None or not str(external_id).strip():
            raise _JSearchNormalizationError(
                "Required JSearch ID missing",
                code="required_id_missing",
                fields=("job_id", "job_uid"),
            )
        location_parts = [record.get("job_city"), record.get("job_state"), record.get("job_country")]
        location = ", ".join(
            part.strip() for part in location_parts if isinstance(part, str) and part.strip()
        )
        workplace = record.get("work_arrangement")
        if not isinstance(workplace, str) and record.get("job_is_remote") is True:
            workplace = "Remoto"
        published_at = _date(record.get("job_posted_at_datetime_utc"))
        if published_at is None and isinstance(record.get("job_posted_at_timestamp"), (int, float)):
            try:
                published_at = datetime.fromtimestamp(record["job_posted_at_timestamp"], UTC)
            except (OverflowError, OSError, ValueError):
                pass
        return NormalizedJob(
            source=self.source_name,
            external_id=_jsearch_external_id(external_id),
            title=title.strip(),
            company=company.strip(),
            description=_plain_text(record.get("job_description")),
            location=location or None,
            workplace_type=workplace.strip() if isinstance(workplace, str) and workplace.strip() else None,
            seniority=(
                record["seniority_level"].strip()
                if isinstance(record.get("seniority_level"), str) and record["seniority_level"].strip()
                else None
            ),
            employment_type=(
                record["job_employment_type"].strip()
                if isinstance(record.get("job_employment_type"), str)
                and record["job_employment_type"].strip()
                else None
            ),
            salary_min=_number(record.get("job_min_salary")),
            salary_max=_number(record.get("job_max_salary")),
            salary_currency=(
                record.get("job_salary_currency")
                if isinstance(record.get("job_salary_currency"), str)
                and len(record["job_salary_currency"]) == 3
                else None
            ),
            published_at=published_at,
            status="open",
            source_url=url.strip(),
            original_payload=record,
        )


class RemotiveDiscoveryAdapter:
    source_name = "remotive"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client

    def search(self, terms: str, limit: int = 25) -> list[NormalizedJob]:
        try:
            response = self._get(REMOTIVE_ROOT, {"search": terms, "limit": limit})
        except httpx.HTTPError as error:
            raise DiscoveryProviderError("Falha de conexão ao consultar Remotive.") from error
        if not 200 <= response.status_code < 300:
            raise DiscoveryProviderError(f"Remotive retornou HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as error:
            raise DiscoveryProviderError("Remotive retornou JSON inválido.") from error
        results = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise DiscoveryProviderError("Remotive retornou uma lista de resultados inválida.")
        try:
            return [self._normalize(record) for record in results[:limit]]
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise DiscoveryProviderError("Remotive retornou dados de vaga inválidos.") from error

    def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        if self.client is not None:
            return self.client.get(url, params=params, headers={"Accept": "application/json"})
        with httpx.Client(timeout=20.0, follow_redirects=False) as client:
            return client.get(url, params=params, headers={"Accept": "application/json"})

    def _normalize(self, record: dict[str, Any]) -> NormalizedJob:
        title = record.get("title")
        company = record.get("company_name")
        url = record.get("url")
        external_id = record.get("id")
        if not all(isinstance(value, str) and value.strip() for value in (title, company, url)):
            raise ValueError("Required Remotive fields missing")
        if external_id is None or not str(external_id).strip():
            raise ValueError("Required Remotive ID missing")
        location = record.get("candidate_required_location")
        return NormalizedJob(
            source=self.source_name,
            external_id=str(external_id),
            title=title.strip(),
            company=company.strip(),
            description=_plain_text(record.get("description")),
            location=location.strip() if isinstance(location, str) and location.strip() else None,
            workplace_type="Remoto",
            employment_type=record.get("job_type") if isinstance(record.get("job_type"), str) else None,
            published_at=_date(record.get("publication_date")),
            status="open",
            source_url=url,
            original_payload=record,
        )


class JobicyDiscoveryAdapter:
    """Public Jobicy remote-jobs API; preserves Jobicy's canonical listing URL."""

    source_name = "jobicy"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client

    def search(self, tag: str, *, geo: str = "brazil", limit: int = 25) -> list[NormalizedJob]:
        try:
            response = self._get({"tag": tag, "geo": geo, "count": limit})
        except httpx.HTTPError as error:
            raise DiscoveryProviderError("Falha de conexão ao consultar Jobicy.") from error
        if not 200 <= response.status_code < 300:
            raise DiscoveryProviderError(f"Jobicy retornou HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as error:
            raise DiscoveryProviderError("Jobicy retornou JSON inválido.") from error
        records = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise DiscoveryProviderError("Jobicy retornou uma lista de resultados inválida.")
        try:
            return [self._normalize(record) for record in records[:limit]]
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise DiscoveryProviderError("Jobicy retornou dados de vaga inválidos.") from error

    def _get(self, params: dict[str, Any]) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if self.client is not None:
            return self.client.get(JOBICY_ROOT, params=params, headers=headers)
        with httpx.Client(timeout=20.0, follow_redirects=False) as client:
            return client.get(JOBICY_ROOT, params=params, headers=headers)

    def _normalize(self, record: dict[str, Any]) -> NormalizedJob:
        title = record.get("jobTitle")
        company = record.get("companyName")
        url = record.get("url")
        external_id = record.get("id")
        if not all(isinstance(value, str) and value.strip() for value in (title, company, url)):
            raise ValueError("Required Jobicy fields missing")
        if external_id is None or not str(external_id).strip():
            raise ValueError("Required Jobicy ID missing")
        salary_min = _number(record.get("salaryMin"))
        salary_max = _number(record.get("salaryMax"))
        salary_currency = record.get("salaryCurrency")
        geo = record.get("jobGeo")
        return NormalizedJob(
            source=self.source_name,
            external_id=str(external_id),
            title=title.strip(),
            company=company.strip(),
            description=_plain_text(record.get("jobDescription")),
            location=geo.strip() if isinstance(geo, str) and geo.strip() else None,
            workplace_type="Remoto",
            seniority=record.get("jobLevel") if isinstance(record.get("jobLevel"), str) else None,
            employment_type=record.get("jobType") if isinstance(record.get("jobType"), str) else None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=(
                salary_currency
                if isinstance(salary_currency, str) and len(salary_currency) == 3
                else None
            ),
            published_at=_date(record.get("pubDate")),
            status="open",
            source_url=url.strip(),
            original_payload=record,
        )


def canonical_query_parameters(parameters: dict[str, Any]) -> str:
    """Stable JSON string for query hashing without credentials."""
    return json.dumps(parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
