import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.services.import_lock import ImportAlreadyRunning, import_lock


def test_import_lock_rejects_a_second_session_for_the_same_database(tmp_path):
    database_path = tmp_path / "jobs.sqlite3"
    engine = create_engine(f"sqlite:///{database_path}")
    first_session = Session(engine)
    second_session = Session(engine)
    first_lock = import_lock(first_session)
    first_lock.__enter__()

    try:
        with pytest.raises(ImportAlreadyRunning):
            with import_lock(second_session):
                pass
    finally:
        first_lock.__exit__(None, None, None)
        first_session.close()
        second_session.close()
        engine.dispose()

    with import_lock(second_session):
        pass
