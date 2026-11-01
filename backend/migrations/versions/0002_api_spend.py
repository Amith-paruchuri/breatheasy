"""Daily Google spend tracking for the spending cap.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_spend",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("searches", sa.Integer, nullable=False, server_default="0"),
        sa.Column("routes_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("aq_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("places_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("est_usd", sa.Float, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("api_spend")
