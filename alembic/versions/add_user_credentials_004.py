"""Add user_credentials table for per-user Tastytrade OAuth storage.

Revision ID: add_user_credentials_004
Revises: add_auth_provider_003
Create Date: 2026-02-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "add_user_credentials_004"
down_revision: Union[str, Sequence[str], None] = "add_auth_provider_003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # Guard: skip if table already exists (e.g., fresh create_all() database)
    if dialect == "sqlite":
        result = conn.execute(sa.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_credentials'"
        ))
        if result.fetchone() is not None:
            return
    else:
        # PostgreSQL
        result = conn.execute(sa.text(
            "SELECT to_regclass('public.user_credentials')"
        ))
        if result.scalar() is not None:
            return

    op.create_table(
        "user_credentials",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("provider", sa.String(50), server_default="tastytrade"),
        sa.Column("encrypted_provider_secret", sa.Text),
        sa.Column("encrypted_refresh_token", sa.Text),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("1") if dialect == "sqlite" else sa.text("true")),
        sa.Column("created_at", sa.String, server_default=sa.func.now()),
        sa.Column("updated_at", sa.String, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_credentials_user_provider"),
    )


def downgrade() -> None:
    op.drop_table("user_credentials")
