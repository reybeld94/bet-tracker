"""drop unique pick per game

Revision ID: 20260212000100
Revises: 20250912000500
Create Date: 2026-02-12 00:01:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260212000100"
down_revision = "20250912000500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("picks") as batch_op:
        batch_op.drop_constraint("uq_picks_game_id", type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("picks") as batch_op:
        batch_op.create_unique_constraint("uq_picks_game_id", ["game_id"])
