"""Alembic env for the pulse-ledger sequence.

The URL comes from config.attributes["database_url"] (how the tests drive it) or the
DATABASE_URL environment variable (how a deploy drives it). The version table is named
per-sequence so this sequence can never collide with ocean's if both ever share a
database — the two-alembic-sequences risk called out in the pulse-ledger-core design.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

database_url = config.attributes.get("database_url") or os.environ["DATABASE_URL"]
# configparser interpolation would choke on a literal % (e.g. a percent-encoded socket path)
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table="alembic_version_pulse_ledger",
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
