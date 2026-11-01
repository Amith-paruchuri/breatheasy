"""Plans: Free / Plus with a monthly street-level search allowance.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("plan", sa.String(16), nullable=False, server_default="free"))
        b.add_column(sa.Column("plus_until", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("razorpay_subscription_id", sa.String(64), nullable=True))
        b.add_column(sa.Column("street_month", sa.String(7), nullable=False, server_default=""))
        b.add_column(sa.Column("street_used", sa.Integer, nullable=False, server_default="0"))
        b.create_index("ix_users_razorpay_sub", ["razorpay_subscription_id"])


def downgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.drop_index("ix_users_razorpay_sub")
        for c in ("street_used", "street_month", "razorpay_subscription_id", "plus_until", "plan"):
            b.drop_column(c)
