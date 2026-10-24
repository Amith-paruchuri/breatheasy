"""Initial schema: users, saved places, trips.

Revision ID: 0001
Revises:
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("google_sub", sa.String(255), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("picture", sa.String(1000), nullable=False),
        sa.Column("session_version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "saved_places",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_saved_places_user", "saved_places", ["user_id"])
    op.create_table(
        "trips",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("departure_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("preference", sa.String(16), nullable=False),
        sa.Column("origin_name", sa.String(200), nullable=False),
        sa.Column("origin_lat", sa.Float, nullable=False),
        sa.Column("origin_lng", sa.Float, nullable=False),
        sa.Column("dest_name", sa.String(200), nullable=False),
        sa.Column("dest_lat", sa.Float, nullable=False),
        sa.Column("dest_lng", sa.Float, nullable=False),
        sa.Column("route_source", sa.String(16), nullable=False),
        sa.Column("duration_s", sa.Float, nullable=False),
        sa.Column("distance_m", sa.Float, nullable=False),
        sa.Column("exposure_pm25", sa.Float),
        sa.Column("fastest_exposure_pm25", sa.Float),
        sa.Column("fastest_duration_s", sa.Float),
        sa.Column("mean_pm25", sa.Float),
        sa.Column("data_source", sa.String(32), nullable=False),
    )
    op.create_index("ix_trips_user_created", "trips", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_trips_user_created", table_name="trips")
    op.drop_table("trips")
    op.drop_index("ix_saved_places_user", table_name="saved_places")
    op.drop_table("saved_places")
    op.drop_table("users")
