"""add provider fields to events

Revision ID: 20250912000400
Revises: 2f9fbfa6aade
Create Date: 2026-02-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250912000400'
down_revision = '2f9fbfa6aade'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("provider", sa.String(), nullable=True))
    op.add_column("events", sa.Column("provider_event_id", sa.String(), nullable=True))
    op.create_unique_constraint(
        "uq_events_provider_event_id",
        "events",
        ["provider", "provider_event_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_events_provider_event_id", "events", type_="unique")
    op.drop_column("events", "provider_event_id")
    op.drop_column("events", "provider")
