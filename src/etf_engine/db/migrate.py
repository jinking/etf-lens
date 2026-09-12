from importlib.resources import files

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect


def run_migrations() -> None:
    with connect(settings.database_path) as con:
        migrations = files("etf_engine.db").joinpath("migrations")
        for migration in sorted(migrations.iterdir(), key=lambda item: item.name):
            if migration.name.endswith(".sql"):
                con.execute(migration.read_text(encoding="utf-8"))
