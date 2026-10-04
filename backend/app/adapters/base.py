from typing import Protocol

from app.schemas.jobs import NormalizedJob


class JobAdapter(Protocol):
    """Interface de leitura comum para fontes que retornam vagas normalizadas."""

    source_name: str

    def fetch_jobs(self) -> list[NormalizedJob]:
        """Coleta vagas e as converte para o contrato canônico."""
