"""Run by Alembic for every upgrade: connects it to the database that
``upgrade`` was called with.
"""

from alembic import context

from bugflow.shared.infrastructure.migrations import VERSION_TABLE

context.configure(
    connection=context.config.attributes["connection"],
    version_table=VERSION_TABLE,
)
with context.begin_transaction():
    context.run_migrations()
