"""add updated_at columns

Revision ID: 20250912000300
Revises: 20250912000200
Create Date: 2025-09-12 00:03:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250912000300"
down_revision = "20250912000200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=True,
            )
        )

    with op.batch_alter_table("picks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("picks") as batch_op:
        batch_op.drop_column("updated_at")

    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("updated_at")
