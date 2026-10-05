import re
import unicodedata
from dataclasses import dataclass

from app.models import Job, ProfessionalProfile
from app.schemas.jobs import JobRecommendation, MatchCriterion


@dataclass(frozen=True)
class _Rule:
    key: str
    label: str
    weight: int


RULES = (
    _Rule("title", "Cargo desejado", 20),
    _Rule("location", "Localização", 10),
    _Rule("work_mode", "Modalidade", 10),
    _Rule("seniority", "Nível", 10),
    _Rule("employment", "Tipo de contrato", 10),
    _Rule("salary", "Faixa salarial", 10),
    _Rule("skills", "Habilidades e experiências", 20),
    _Rule("must_have", "Critérios obrigatórios", 10),
)


def _normalize(value: str) -> str:
    value = re.sub(r"(?<!\w)c\+\+(?!\w)", "cplusplus", value, flags=re.IGNORECASE)
    value = re.sub(r"(?<!\w)c#(?!\w)", "csharp", value, flags=re.IGNORECASE)
    value = re.sub(r"\.net\b", "dotnet", value, flags=re.IGNORECASE)
    value = re.sub(r"\bnode\.js\b", "nodejs", value, flags=re.IGNORECASE)
    decomposed = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", decomposed.casefold()))


def _terms(value: str | None) -> list[str]:
    if not value:
        return []
    return [term.strip() for term in re.split(r"[,;|\n]+", value) if term.strip()]


def _contains(text: str, term: str) -> bool:
    normalized_text = f" {_normalize(text)} "
    normalized_term = f" {_normalize(term)} "
    return normalized_term.strip() != "" and normalized_term in normalized_text


def _mode_term(term: str) -> str:
    normalized = _normalize(term)
    synonyms = {
        "remoto": "remote",
        "remota": "remote",
        "home office": "remote",
        "hibrido": "hybrid",
        "hibrida": "hybrid",
        "presencial": "onsite",
        "no escritorio": "onsite",
    }
    return synonyms.get(normalized, normalized)


def _match_terms(text: str, terms: list[str], *, mode: bool = False) -> list[str]:
    if mode:
        normalized_text = _mode_term(text)
        return [term for term in terms if _mode_term(term) in normalized_text]
    return [term for term in terms if _contains(text, term)]


def _infer_work_mode(job: Job) -> str:
    if job.workplace_type:
        return job.workplace_type
    evidence = " ".join(part for part in (job.title, job.description) if part)
    aliases = {
        "remote": ("remote", "remoto", "home office"),
        "hybrid": ("hybrid", "hibrido"),
        "onsite": ("onsite", "presencial", "on site"),
    }
    return next(
        (mode for mode, terms in aliases.items() if any(_contains(evidence, term) for term in terms)),
        "",
    )


def _criterion(rule: _Rule, result: str, explanation: str, ratio: float | None = None) -> MatchCriterion:
    return MatchCriterion(
        key=rule.key,
        label=rule.label,
        result=result,
        weight=rule.weight,
        points=round(rule.weight * ratio) if ratio is not None else (rule.weight if result == "match" else 0),
        explanation=explanation,
    )


def analyze_job(job: Job, profile: ProfessionalProfile) -> JobRecommendation:
    preference = profile.preference
    criteria: list[MatchCriterion] = []
    strengths: list[str] = []
    gaps: list[str] = []
    excluded_reasons: list[str] = []
    available_weight = 0
    earned_points = 0
    evidence_weight = 0
    job_text = " ".join(
        part
        for part in (
            job.title,
            job.description,
            job.location or "",
            job.workplace_type or "",
            job.seniority or "",
            job.employment_type or "",
        )
        if part
    )

    def add(
        rule: _Rule,
        result: str,
        explanation: str,
        ratio: float | None = None,
        evidence_ratio: float | None = None,
    ) -> None:
        nonlocal available_weight, earned_points, evidence_weight
        criteria.append(_criterion(rule, result, explanation, ratio))
        if result != "unknown":
            available_weight += rule.weight
            earned_points += criteria[-1].points
            evidence_weight += round(rule.weight * (evidence_ratio if evidence_ratio is not None else 1))
        if result == "match":
            strengths.append(explanation)
        elif result == "mismatch":
            gaps.append(explanation)

    desired_titles = _terms(preference.desired_titles) if preference else []
    if desired_titles and job.title:
        matches = _match_terms(job.title, desired_titles)
        add(
            RULES[0],
            "match" if matches else "mismatch",
            f"Cargo compatível com {', '.join(matches)}."
            if matches
            else "O cargo não corresponde aos títulos desejados.",
        )
    else:
        add(RULES[0], "unknown", "Não há cargo desejado configurado para comparar.")

    desired_locations = _terms(preference.desired_locations) if preference else []
    if desired_locations and job.location:
        matches = _match_terms(job.location, desired_locations)
        add(
            RULES[1],
            "match" if matches else "mismatch",
            f"Localização compatível com {', '.join(matches)}."
            if matches
            else "A localização da vaga difere das preferências.",
        )
    else:
        add(RULES[1], "unknown", "Localização da vaga ou preferência não informada.")

    desired_modes = _terms(preference.work_modes) if preference else []
    actual_mode = _infer_work_mode(job)
    if desired_modes and actual_mode:
        matches = _match_terms(actual_mode, desired_modes, mode=True)
        add(
            RULES[2],
            "match" if matches else "mismatch",
            f"Modalidade compatível com {', '.join(matches)}."
            if matches
            else "A modalidade anunciada difere das preferências.",
        )
    else:
        add(RULES[2], "unknown", "Modalidade da vaga ou preferência não informada.")

    desired_seniority = _terms(preference.seniority) if preference else []
    actual_seniority = job.seniority or ""
    if not actual_seniority:
        seniority_aliases = (
            "estagio",
            "junior",
            "entry level",
            "pleno",
            "mid level",
            "senior",
            "lead",
            "staff",
        )
        actual_seniority = next((alias for alias in seniority_aliases if _contains(job.title, alias)), "")
    if desired_seniority and actual_seniority:
        matches = _match_terms(actual_seniority, desired_seniority)
        add(
            RULES[3],
            "match" if matches else "mismatch",
            f"Nível compatível com {', '.join(matches)}."
            if matches
            else "O nível anunciado difere do nível desejado.",
        )
    else:
        add(RULES[3], "unknown", "Nível da vaga ou preferência não informado.")

    desired_employment = _terms(preference.employment_types) if preference else []
    actual_employment = job.employment_type or ""
    if not actual_employment:
        employment_aliases = ("clt", "pj", "estagio", "contract", "full time", "part time", "temporario")
        actual_employment = next((alias for alias in employment_aliases if _contains(job_text, alias)), "")
    if desired_employment and actual_employment:
        matches = _match_terms(actual_employment, desired_employment)
        add(
            RULES[4],
            "match" if matches else "mismatch",
            f"Contrato compatível com {', '.join(matches)}."
            if matches
            else "O tipo de contrato difere das preferências.",
        )
    else:
        add(RULES[4], "unknown", "Tipo de contrato da vaga ou preferência não informado.")

    salary_preferences = preference and (
        preference.minimum_salary is not None or preference.maximum_salary is not None
    )
    salary_available = job.salary_min is not None or job.salary_max is not None
    same_currency = (
        preference is not None
        and job.salary_currency is not None
        and preference.salary_currency.casefold() == job.salary_currency.casefold()
    )
    if salary_preferences and salary_available and same_currency:
        confirmed_below = (
            job.salary_max is not None
            and preference.minimum_salary is not None
            and job.salary_max < preference.minimum_salary
        )
        confirmed_above = (
            job.salary_min is not None
            and preference.maximum_salary is not None
            and job.salary_min > preference.maximum_salary
        )
        if confirmed_below or confirmed_above:
            add(RULES[5], "mismatch", "Faixa salarial anunciada está fora da preferência.")
        elif job.salary_min is not None and job.salary_max is not None:
            add(RULES[5], "match", "Faixa salarial anunciada atende à preferência.")
        else:
            add(
                RULES[5],
                "partial",
                "A faixa salarial é parcial; não há dados para confirmar todos os limites.",
                0.5,
                0.5,
            )
    else:
        add(RULES[5], "unknown", "Salário, moeda ou faixa desejada insuficiente para comparar.")

    profile_terms = _terms(profile.skills)
    profile_terms.extend(exp.role for exp in profile.experiences if exp.role)
    profile_terms = list(dict.fromkeys(profile_terms))
    if profile_terms and job_text.strip():
        matched_skills = _match_terms(job_text, profile_terms)
        ratio = len(matched_skills) / len(profile_terms)
        explanation = (
            f"Termos do perfil encontrados no anúncio: {', '.join(matched_skills[:5])}."
            if matched_skills
            else "Nenhuma habilidade ou experiência do perfil foi identificada no anúncio."
        )
        add(
            RULES[6],
            "match" if ratio == 1 else "partial" if ratio > 0 else "unknown",
            explanation,
            ratio if matched_skills else None,
        )
        if matched_skills and ratio < 1:
            strengths.append(explanation)
    else:
        add(RULES[6], "unknown", "Perfil sem habilidades ou anúncio sem texto para comparar.")

    must_have = _terms(preference.must_have) if preference else []
    if must_have and job_text.strip():
        found = _match_terms(job_text, must_have)
        ratio = len(found) / len(must_have)
        add(
            RULES[7],
            "match" if ratio == 1 else "partial" if ratio > 0 else "unknown",
            f"Critérios obrigatórios encontrados no anúncio: {', '.join(found)}."
            if found
            else "Critérios obrigatórios não foram identificados no anúncio.",
            ratio if found else None,
            evidence_ratio=ratio if found else 0,
        )
        gaps.extend(f"{term} não foi identificado no anúncio." for term in must_have if term not in found)
    else:
        add(RULES[7], "unknown", "Não há critérios obrigatórios ou texto do anúncio para comparar.")

    excluded_terms = _terms(preference.excluded_criteria) if preference else []
    excluded_hits = _match_terms(job_text, excluded_terms) if job_text.strip() else []
    if excluded_hits:
        excluded_reasons.extend(f"Critério excluído encontrado: {term}." for term in excluded_hits)

    score = round(earned_points / available_weight * 100) if available_weight else 0
    if excluded_reasons:
        score = 0
        gaps.extend(excluded_reasons)
    coverage = round(evidence_weight)
    return JobRecommendation(
        job=job,
        score=score,
        coverage=coverage,
        excluded=bool(excluded_reasons),
        strengths=strengths,
        gaps=gaps,
        criteria=criteria,
    )


def rank_jobs(
    jobs: list[Job],
    profile: ProfessionalProfile,
    *,
    min_score: int = 0,
    location: str | None = None,
    workplace_type: str | None = None,
    status: str = "open",
    include_excluded: bool = True,
) -> list[JobRecommendation]:
    recommendations = [analyze_job(job, profile) for job in jobs]
    filtered = []
    for recommendation in recommendations:
        job = recommendation.job
        if recommendation.score < min_score:
            continue
        if recommendation.excluded and not include_excluded:
            continue
        if status != "all" and job.status != status:
            continue
        if location and not _contains(job.location or "", location):
            continue
        if workplace_type and _mode_term(_infer_work_mode(job)) != _mode_term(workplace_type):
            continue
        filtered.append(recommendation)
    return sorted(
        filtered,
        key=lambda item: (
            item.excluded,
            -item.score,
            -(item.coverage),
            item.job.published_at is None,
            -(item.job.published_at.timestamp()) if item.job.published_at else 0,
            item.job.id,
        ),
    )
