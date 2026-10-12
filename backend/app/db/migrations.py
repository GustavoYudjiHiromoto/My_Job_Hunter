from sqlalchemy import Engine, inspect


def upgrade_schema(engine: Engine) -> None:
    """Aplica alterações pequenas necessárias a bancos SQLite criados por versões anteriores."""
    if engine.dialect.name != "sqlite":
        return
    columns = {column["name"] for column in inspect(engine).get_columns("preferences")}
    with engine.begin() as connection:
        for name in ("search_keywords", "search_areas"):
            if name not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE preferences ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"
                )
