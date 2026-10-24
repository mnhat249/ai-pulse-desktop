from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from app.storage.tables import metadata

config = context.config
url = config.get_main_option("sqlalchemy.url")
assert url is not None

if context.is_offline_mode():
    context.configure(url=url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
