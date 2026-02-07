"""event pick contract

Revision ID: 20250912000200
Revises: 20250912000100
Create Date: 2025-09-12 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250912000200"
down_revision = "20250912000100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("league", sa.String(), nullable=False),
        sa.Column("home_team", sa.String(), nullable=False),
        sa.Column("away_team", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
    )
    op.create_index("ix_events_id", "events", ["id"], unique=False)

    with op.batch_alter_table("picks") as batch_op:
        batch_op.add_column(sa.Column("event_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("sportsbook", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("market_type", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("period", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("line", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("side", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("recommendation", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("status", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_picks_event_id_events",
            "events",
            ["event_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("picks") as batch_op:
        batch_op.drop_constraint("fk_picks_event_id_events", type_="foreignkey")
        batch_op.drop_column("status")
        batch_op.drop_column("recommendation")
        batch_op.drop_column("side")
        batch_op.drop_column("line")
        batch_op.drop_column("period")
        batch_op.drop_column("market_type")
        batch_op.drop_column("sportsbook")
        batch_op.drop_column("event_id")

    op.drop_index("ix_events_id", table_name="events")
    op.drop_table("events")
