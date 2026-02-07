"""initial

Revision ID: 20250912000100
Revises: 
Create Date: 2025-09-12 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250912000100"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "picks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("sport", sa.String(), nullable=True),
        sa.Column("event", sa.String(), nullable=True),
        sa.Column("market", sa.String(), nullable=True),
        sa.Column("selection", sa.String(), nullable=True),
        sa.Column("odds", sa.Float(), nullable=True),
        sa.Column("stake", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("gpt_name", sa.String(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("result", sa.String(), nullable=True),
        sa.Column("profit", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
    )
    op.create_index("ix_picks_id", "picks", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_picks_id", table_name="picks")
    op.drop_table("picks")
