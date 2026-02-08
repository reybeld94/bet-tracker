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
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("provider", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("provider_event_id", sa.String(), nullable=True))
    op.create_index(
        "ux_events_provider_event_id",
        "events",
        ["provider", "provider_event_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_events_provider_event_id", table_name="events")
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("provider_event_id")
        batch_op.drop_column("provider")
