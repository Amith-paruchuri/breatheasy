"""Best time to leave, in the trip benchmark.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("benchmark_trips", sa.Column("now_pm25", sa.Float))
    op.add_column("benchmark_trips", sa.Column("best_time_pm25", sa.Float))
    op.add_column("benchmark_trips", sa.Column("best_offset_min", sa.Integer))


def downgrade() -> None:
    op.drop_column("benchmark_trips", "best_offset_min")
    op.drop_column("benchmark_trips", "best_time_pm25")
    op.drop_column("benchmark_trips", "now_pm25")
