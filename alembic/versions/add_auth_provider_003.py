"""Add auth_provider column to users table.

Revision ID: add_auth_provider_003
Revises: drop_chain_merges_002
Create Date: 2026-02-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "add_auth_provider_003"
down_revision: Union[str, Sequence[str], None] = "drop_chain_merges_002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guard: skip if column already exists (e.g., fresh create_all() database)
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        result = conn.execute(sa.text("PRAGMA table_info('users')"))
        columns = [row[1] for row in result]
        if "auth_provider" not in columns:
            op.add_column("users", sa.Column("auth_provider", sa.String(20), nullable=True))
    else:
        # PostgreSQL
        result = conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'auth_provider'"
        ))
        if result.fetchone() is None:
            op.add_column("users", sa.Column("auth_provider", sa.String(20), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        # SQLite doesn't support DROP COLUMN before 3.35.0; skip if not available
        result = conn.execute(sa.text("PRAGMA table_info('users')"))
        columns = [row[1] for row in result]
        if "auth_provider" in columns:
            try:
                op.drop_column("users", "auth_provider")
            except Exception:
                pass  # Old SQLite without DROP COLUMN support
    else:
        op.drop_column("users", "auth_provider")
