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
        batch_op.create_unique_constraint(
            "uq_events_provider_event_id",
            ["provider", "provider_event_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_constraint("uq_events_provider_event_id", type_="unique")
        batch_op.drop_column("provider_event_id")
        batch_op.drop_column("provider")
