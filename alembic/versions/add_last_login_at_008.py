"""Drop last_login_at column from users table.

Column was added then reverted — using updated_at for login tracking instead.

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
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("last_login_at")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("last_login_at", sa.String(), nullable=True))
