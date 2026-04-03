"""Add opened_at to accounts table

Revision ID: 9264427376c0
Revises: add_volatility_metrics_018
Create Date: 2026-04-02 22:25:04.469352

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9264427376c0'
down_revision: Union[str, Sequence[str], None] = 'add_volatility_metrics_018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add opened_at column to accounts table."""
    op.add_column('accounts', sa.Column('opened_at', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove opened_at column from accounts table."""
    op.drop_column('accounts', 'opened_at')
