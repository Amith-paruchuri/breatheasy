"""Validation samples against CPCB stations, and anonymous usage counts.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "validation_samples",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("station", sa.String(200), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False),
        sa.Column("station_updated", sa.String(40)),
        sa.Column("station_pm25", sa.Float, nullable=False),
        sa.Column("google_pm25", sa.Float, nullable=False),
        sa.Column("adjusted_pm25", sa.Float, nullable=False),
        sa.Column("hours", sa.Integer, nullable=False),
        sa.Column("near_road", sa.Boolean, nullable=False),
        sa.Column("near_green", sa.Boolean, nullable=False),
        sa.Column("street_layer", sa.Boolean, nullable=False),
    )
    op.create_index("ix_validation_samples_run_at", "validation_samples", ["run_at"])
    op.create_table(
        "usage_counts",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("event", sa.String(24), primary_key=True),
        sa.Column("city", sa.String(40), primary_key=True),
        sa.Column("n", sa.Integer, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("usage_counts")
    op.drop_index("ix_validation_samples_run_at", "validation_samples")
    op.drop_table("validation_samples")
