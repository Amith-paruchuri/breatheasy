"""Trip benchmark results.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "benchmark_trips",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("city", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("origin", sa.String(80), nullable=False),
        sa.Column("destination", sa.String(80), nullable=False),
        sa.Column("routes", sa.Integer, nullable=False),
        sa.Column("fastest_min", sa.Float, nullable=False),
        sa.Column("chosen_min", sa.Float, nullable=False),
        sa.Column("fastest_pm25", sa.Float),
        sa.Column("chosen_pm25", sa.Float),
        sa.Column("fastest_bad_min", sa.Float),
        sa.Column("chosen_bad_min", sa.Float),
        sa.Column("bad_level", sa.Integer),
        sa.Column("chosen_green_min", sa.Float),
        sa.Column("fastest_green_min", sa.Float),
        sa.Column("chosen_road_min", sa.Float),
        sa.Column("fastest_road_min", sa.Float),
        sa.Column("differs", sa.Boolean, nullable=False),
        sa.Column("fidelity3", sa.Float),
        sa.Column("fidelity8", sa.Float),
    )
    op.create_index("ix_benchmark_trips_run_at", "benchmark_trips", ["run_at"])


def downgrade() -> None:
    op.drop_index("ix_benchmark_trips_run_at", "benchmark_trips")
    op.drop_table("benchmark_trips")
