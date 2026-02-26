"""Add last_login_at column to users table.

Tracks when each user last authenticated. Updated on every
authenticated API request via ensure_user_exists().

Revision ID: add_last_login_at_008
Revises: fix_business_key_pks_007
Create Date: 2026-02-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "add_last_login_at_008"
down_revision: Union[str, Sequence[str], None] = "fix_business_key_pks_007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
