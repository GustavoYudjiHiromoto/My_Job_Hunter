from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DATABASE_URL


def create_app_engine(database_url: str):
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
    app_engine = create_engine(database_url, connect_args=connect_args)
    if is_sqlite:
        @event.listens_for(app_engine, "connect")
        def set_sqlite_concurrency_pragmas(connection, _record):
            # Wait for short concurrent writes (profile edits vs. collection) instead of
            # immediately failing with SQLITE_BUSY / "database is locked".
            connection.execute("PRAGMA busy_timeout=30000")
            # WAL lets readers continue while a writer commits. SQLite still serializes
            # writers; the import lock and busy timeout cover that remaining constraint.
            if database_url.startswith("sqlite:///") and not database_url.endswith(":memory:"):
                connection.execute("PRAGMA journal_mode=WAL")

    return app_engine


engine = create_app_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session]:
    with SessionLocal() as session:
        yield session
