"""Alembic env.py — reads DATABASE_URL from environment for migration runs."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers defaults True, which silently kills every logger already
    # imported by the process — in the combined test run, the migration fixtures were
    # disabling other packages' loggers mid-suite.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = None

# Read DATABASE_URL from environment; strip +asyncpg for sync Alembic runner
database_url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
