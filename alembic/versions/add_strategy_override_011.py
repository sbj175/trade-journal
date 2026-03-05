"""Add strategy_label_user_override to position_groups.

Revision ID: add_strategy_override_011
Revises: add_waitlist_010
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "add_strategy_override_011"
down_revision: Union[str, Sequence[str], None] = "add_waitlist_010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "position_groups",
        sa.Column("strategy_label_user_override", sa.Boolean(), server_default=sa.false(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("position_groups", "strategy_label_user_override")
