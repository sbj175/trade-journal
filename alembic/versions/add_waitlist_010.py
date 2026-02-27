"""Add waitlist_entries table for beta capacity gate.

Revision ID: add_waitlist_010
Revises: add_tags_009
Create Date: 2026-02-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "add_waitlist_010"
down_revision: Union[str, Sequence[str], None] = "add_tags_009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    dialect = conn.dialect.name
    if dialect == "sqlite":
        result = conn.execute(sa.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
        ), {"t": table_name})
        return result.fetchone() is not None
    else:
        result = conn.execute(sa.text(
            "SELECT to_regclass(:t)"
        ), {"t": f"public.{table_name}"})
        return result.scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "waitlist_entries"):
        return

    op.create_table(
        "waitlist_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String, unique=True, nullable=False),
        sa.Column("created_at", sa.String, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("waitlist_entries")
