from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

import app.models  # noqa: F401 — register models on Base
from app.database import DATABASE_URL, Base

config = context.config

# The URL normally comes from the app's DATABASE_URL, but an explicit
# sqlalchemy.url set by the caller wins. That is what lets the migration test
# run the chain against a throwaway database instead of the app's own.
url = config.get_main_option("sqlalchemy.url", None) or DATABASE_URL
config.set_main_option("sqlalchemy.url", url)

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# render_as_batch keeps ALTERs expressible on SQLite, which has no real ALTER.
# Postgres is unaffected — batch mode emits plain ALTERs there.
_BATCH = True


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=_BATCH,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, future=True)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_BATCH,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
