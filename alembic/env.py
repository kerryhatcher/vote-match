"""Alembic environment configuration for Vote Match."""

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Import Vote Match components
from vote_match.config import get_settings
from vote_match.models import Base

# Alembic Config object
config = context.config

# Set up Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata from Vote Match models
target_metadata = Base.metadata

# Get database URL from Vote Match settings
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def include_object(_object, name, type_, _reflected, _compare_to):
    """Filter out Django/Wagtail tables and other non-project tables.

    Only include tables that are defined in our Vote Match models.
    """
    # List of table prefixes to ignore
    ignore_prefixes = [
        "auth_",
        "django_",
        "wagtail",
        "taggit_",
        "world_",
        "checkin_",
        "public",  # Ignore 'public' table if it exists
    ]

    # For tables, check if they should be included
    if type_ == "table":
        # Ignore tables with specific prefixes
        for prefix in ignore_prefixes:
            if name.startswith(prefix):
                return False

        # Ignore alembic_version table (managed by Alembic itself)
        if name == "alembic_version":
            return False

    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=False,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=False,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
