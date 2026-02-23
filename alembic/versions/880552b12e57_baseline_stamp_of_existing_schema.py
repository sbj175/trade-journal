"""baseline stamp of existing schema

Revision ID: 880552b12e57
Revises:
Create Date: 2026-02-23

This is a no-op baseline migration. The existing SQLite schema was created by
db_manager.initialize_database() and _add_transaction_columns(). This migration
stamps the existing database so that future Alembic migrations start from a
known revision.

To stamp an existing database:
    alembic stamp head
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '880552b12e57'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Baseline — existing schema already matches models.py.
    # Run `alembic stamp head` on existing databases.
    pass


def downgrade() -> None:
    # Cannot downgrade past the baseline.
    pass
