import argparse
import json
import logging
import sys

from app import models  # noqa: F401 - registra modelos adicionais no metadata.
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import ImportRun
from app.schemas.jobs import ImportRunRead
from app.services.jobs import run_import


def _exit_code(run: ImportRun) -> int:
    if run.status == "succeeded":
        return 0
    if run.status == "partial":
        return 2
    if run.status == "skipped":
        return 3
    failed_sources = [result for result in run.sources if result.status == "failed"]
    configuration_error = run.error == "Nenhuma fonte configurada para esta execução." or (
        bool(failed_sources)
        and all(
            result.error and ("caracteres inválidos" in result.error or "região Lever" in result.error)
            for result in failed_sources
        )
    )
    if run.status == "failed" and configuration_error:
        return 4
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta vagas nas fontes configuradas do Job Hunter.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser("import-jobs", help="Executa uma coleta de vagas.")
    import_parser.add_argument(
        "--source", choices=("all", "greenhouse", "lever"), default="all", help="Fontes a consultar."
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)

    with SessionLocal() as db:
        Base.metadata.create_all(bind=engine)
        run = run_import(db, args.source)
        result = ImportRunRead.model_validate(run)
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False))
        return _exit_code(run)


if __name__ == "__main__":
    raise SystemExit(main())
