"""Add symbol_volatility_metrics table for realized volatility.

Revision ID: add_volatility_metrics_018
Revises: add_historical_prices_017
"""

import sqlalchemy as sa
from alembic import op

revision: str = "add_volatility_metrics_018"
down_revision: str = "add_historical_prices_017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "symbol_volatility_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("rv10", sa.Float()),
        sa.Column("rv20", sa.Float()),
        sa.Column("rv30", sa.Float()),
        sa.UniqueConstraint("symbol", "date", name="uq_volatility_metric_symbol_date"),
    )
    op.create_index(
        "idx_volatility_metrics_symbol_date",
        "symbol_volatility_metrics",
        ["symbol", "date"],
    )


def downgrade() -> None:
    op.drop_index("idx_volatility_metrics_symbol_date", table_name="symbol_volatility_metrics")
    op.drop_table("symbol_volatility_metrics")
