"""Add historical_prices table for EOD price caching.

Revision ID: add_historical_prices_016
Revises: drop_source_chain_id_015
"""

import sqlalchemy as sa
from alembic import op

revision: str = "add_historical_prices_016"
down_revision: str = "drop_source_chain_id_015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_prices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("open", sa.Float()),
        sa.Column("high", sa.Float()),
        sa.Column("low", sa.Float()),
        sa.Column("close", sa.Float()),
        sa.Column("adj_close", sa.Float()),
        sa.Column("volume", sa.Integer()),
        sa.UniqueConstraint("symbol", "date", name="uq_historical_price_symbol_date"),
    )
    op.create_index(
        "idx_historical_prices_symbol_date",
        "historical_prices",
        ["symbol", "date"],
    )


def downgrade() -> None:
    op.drop_index("idx_historical_prices_symbol_date", table_name="historical_prices")
    op.drop_table("historical_prices")
