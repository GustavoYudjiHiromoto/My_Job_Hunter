from sqlalchemy import text

from app.db.session import create_app_engine


def test_sqlite_engine_waits_for_transient_write_locks(tmp_path):
    database = tmp_path / "busy-timeout.sqlite3"
    engine = create_app_engine(f"sqlite:///{database.as_posix()}")
    try:
        with engine.connect() as connection:
            timeout_ms = connection.scalar(text("PRAGMA busy_timeout"))
            assert timeout_ms == 30000
            journal_mode = connection.scalar(text("PRAGMA journal_mode"))
            assert journal_mode.casefold() == "wal"
    finally:
        engine.dispose()
