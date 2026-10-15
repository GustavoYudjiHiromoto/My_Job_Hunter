import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "job_hunter.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}")


def get_greenhouse_board_tokens() -> list[str]:
    """Lista os identificadores públicos dos boards configurados no ambiente."""
    raw_tokens = os.getenv("GREENHOUSE_BOARDS", "")
    return list(dict.fromkeys(token.strip() for token in raw_tokens.split(",") if token.strip()))


def get_lever_sites() -> list[str]:
    """Lista os sites Lever públicos configurados no ambiente."""
    raw_sites = os.getenv("LEVER_SITES", "")
    return list(dict.fromkeys(site.strip() for site in raw_sites.split(",") if site.strip()))


def get_lever_region() -> str:
    """Retorna a região da API Lever configurada (global ou eu)."""
    return os.getenv("LEVER_REGION", "global").strip().casefold()


def get_jsearch_api_key() -> str:
    """Retorna a chave opcional do JSearch sem expô-la em respostas."""
    return os.getenv("JSEARCH_API_KEY", "").strip()


def get_openai_api_key() -> str:
    """Retorna a chave opcional do provider de análise por IA."""
    return os.getenv("OPENAI_API_KEY", "").strip()


def get_openai_model() -> str:
    """Modelo usado na avaliação manual de compatibilidade por IA."""
    return os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
