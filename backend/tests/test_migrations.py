from sqlalchemy import create_engine, inspect, text

from app.db.migrations import upgrade_schema


def test_sqlite_preferences_upgrade_is_idempotent_and_preserves_existing_values(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE preferences (id INTEGER PRIMARY KEY, desired_titles TEXT NOT NULL DEFAULT '')"
        )
        connection.exec_driver_sql(
            "INSERT INTO preferences (id, desired_titles) VALUES (1, 'Backend Developer')"
        )

    upgrade_schema(engine)
    upgrade_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("preferences")}
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT desired_titles, search_keywords, search_areas FROM preferences WHERE id = 1")
        ).one()
    assert {"search_keywords", "search_areas"}.issubset(columns)
    assert row == ("Backend Developer", "", "")
    engine.dispose()
