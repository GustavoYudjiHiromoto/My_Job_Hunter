import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "job_hunter.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}")


def get_greenhouse_board_tokens() -> list[str]:
    """Lista os identificadores públicos dos boards configurados no ambiente."""
    raw_tokens = os.getenv("GREENHOUSE_BOARDS", "")
    return list(dict.fromkeys(token.strip() for token in raw_tokens.split(",") if token.strip()))
