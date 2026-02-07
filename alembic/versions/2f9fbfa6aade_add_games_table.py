"""add games table

Revision ID: 2f9fbfa6aade
Revises: 20250912000300
Create Date: 2026-02-07 18:29:22.852288

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2f9fbfa6aade'
down_revision = '20250912000300'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_event_id", sa.String(), nullable=False),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("league", sa.String(), nullable=False),
        sa.Column("start_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("home_team", sa.String(), nullable=False),
        sa.Column("away_team", sa.String(), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_games_provider_event_id"),
    )
    op.create_index(op.f("ix_games_id"), "games", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_games_id"), table_name="games")
    op.drop_table("games")
