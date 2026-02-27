"""Add tags and position_group_tags tables for group tagging.

Revision ID: add_tags_009
Revises: add_last_login_at_008
Create Date: 2026-02-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "add_tags_009"
down_revision: Union[str, Sequence[str], None] = "add_last_login_at_008"
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

    if not _table_exists(conn, "tags"):
        op.create_table(
            "tags",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True, index=True),
            sa.Column("name", sa.String, nullable=False),
            sa.Column("color", sa.String),
            sa.Column("created_at", sa.String, server_default=sa.func.now()),
            sa.Column("updated_at", sa.String, server_default=sa.func.now()),
            sa.UniqueConstraint("name", "user_id", name="uq_tags_name_user"),
        )

    if not _table_exists(conn, "position_group_tags"):
        op.create_table(
            "position_group_tags",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True, index=True),
            sa.Column("group_id", sa.String, nullable=False),
            sa.Column("tag_id", sa.Integer, sa.ForeignKey("tags.id"), nullable=False),
            sa.Column("created_at", sa.String, server_default=sa.func.now()),
            sa.UniqueConstraint("group_id", "tag_id", "user_id", name="uq_position_group_tags_group_tag_user"),
            sa.Index("idx_position_group_tags_group", "group_id"),
            sa.Index("idx_position_group_tags_tag", "tag_id"),
        )


def downgrade() -> None:
    op.drop_table("position_group_tags")
    op.drop_table("tags")
