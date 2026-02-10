"""add auto picks tables"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250912000500"
down_revision = "2f9fbfa6aade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("openai_api_key_enc", sa.Text(), nullable=True),
        sa.Column("openai_model", sa.String(), nullable=False, server_default="gpt-5"),
        sa.Column(
            "openai_reasoning_effort",
            sa.String(),
            nullable=False,
            server_default="high",
        ),
        sa.Column("auto_picks_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auto_picks_concurrency", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("auto_picks_poll_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("auto_picks_max_retries", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("allow_totals_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "pick_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False),
        sa.Column("run_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_owner", sa.String(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("game_id", name="uq_pick_jobs_game_id"),
    )
    op.create_index("ix_pick_jobs_status_run_at", "pick_jobs", ["status", "run_at_utc"])

    op.drop_table("picks")
    op.create_table(
        "picks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False),
        sa.Column("result", sa.String(), nullable=False, server_default="NO_BET"),
        sa.Column("market", sa.String(), nullable=True),
        sa.Column("emoji", sa.String(), nullable=False, server_default=""),
        sa.Column("selection", sa.String(), nullable=True),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("odds_format", sa.String(), nullable=True),
        sa.Column("odds", sa.Float(), nullable=True),
        sa.Column("p_est", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p_implied", sa.Float(), nullable=True),
        sa.Column("ev", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stake_u", sa.Float(), nullable=False, server_default="0"),
        sa.Column("high_prob_low_payout", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_value", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("risks_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("triggers_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("missing_data_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("as_of_utc", sa.String(), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw_ai_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("game_id", name="uq_picks_game_id"),
    )


def downgrade() -> None:
    op.drop_table("picks")
    op.drop_index("ix_pick_jobs_status_run_at", table_name="pick_jobs")
    op.drop_table("pick_jobs")
    op.drop_table("app_settings")

    op.create_table(
        "picks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=True),
        sa.Column("sportsbook", sa.String(), server_default=""),
        sa.Column("market_type", sa.String(), server_default=""),
        sa.Column("period", sa.String(), server_default="FG"),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("side", sa.String(), server_default=""),
        sa.Column("odds", sa.Float(), server_default="0"),
        sa.Column("stake", sa.Float(), server_default="0"),
        sa.Column("recommendation", sa.String(), server_default=""),
        sa.Column("status", sa.String(), server_default="DRAFT"),
        sa.Column("source", sa.String(), server_default="AI"),
        sa.Column("gpt_name", sa.String(), server_default=""),
        sa.Column("reasoning", sa.Text(), server_default=""),
        sa.Column("result", sa.String(), server_default="PENDING"),
        sa.Column("profit", sa.Float(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
